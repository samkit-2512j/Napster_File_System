import socket
import threading
from pathlib import Path

from file_handler import get_file_path, list_shared_files
from protocol import make_request, make_response, recv_json, send_json

HEARTBEAT_INTERVAL = 5
CHUNK_SIZE = 64 * 1024


def prompt_int(prompt, default):
    while True:
        raw = input(prompt).strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            print("Enter a valid number.")


def format_size(num_bytes):
    size = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def unique_download_path(download_dir, filename):
    download_path = Path(download_dir)
    download_path.mkdir(parents=True, exist_ok=True)
    target = download_path / filename
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    for i in range(1, 1000):
        candidate = download_path / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("Unable to create a unique filename")


def send_server_request(host, port, message, timeout=5):
    with socket.create_connection((host, port), timeout=timeout) as sock:
        send_json(sock, message)
        return recv_json(sock)


def register_with_server(host, port, listen_port, shared_dir):
    files = list_shared_files(shared_dir)
    message = make_request("REGISTER", {"listen_port": listen_port, "files": files})
    response = send_server_request(host, port, message)
    return response, files


def search_server(host, port, query):
    message = make_request("SEARCH", {"query": query})
    response = send_server_request(host, port, message)
    if response.get("status") != "OK":
        print(f"Search failed: {response.get('error', 'unknown error')}")
        return []
    payload = response.get("payload") or {}
    return payload.get("results", [])


def send_heartbeat(host, port, listen_port):
    message = make_request("HEARTBEAT", {"listen_port": listen_port})
    response = send_server_request(host, port, message)
    return response.get("status") == "OK"


def deregister(host, port, listen_port):
    message = make_request("DEREGISTER", {"listen_port": listen_port})
    try:
        send_server_request(host, port, message)
    except Exception:
        return


def heartbeat_loop(host, port, listen_port, stop_event):
    failures = 0
    while not stop_event.is_set():
        try:
            ok = send_heartbeat(host, port, listen_port)
            failures = 0 if ok else failures + 1
        except Exception:
            failures += 1
        if failures >= 3:
            print("WARNING: Lost contact with index server.")
        stop_event.wait(HEARTBEAT_INTERVAL)


def receive_to_file(sock, file_path, total_size):
    remaining = total_size
    with open(file_path, "wb") as handle:
        while remaining > 0:
            chunk = sock.recv(min(CHUNK_SIZE, remaining))
            if not chunk:
                raise ConnectionError("Transfer interrupted")
            handle.write(chunk)
            remaining -= len(chunk)


def download_from_peer(peer, filename, download_dir):
    address = (peer["ip"], peer["port"])
    with socket.create_connection(address, timeout=10) as sock:
        request = make_request("DOWNLOAD_REQUEST", {"filename": filename})
        send_json(sock, request)
        response = recv_json(sock)
        if response.get("status") != "OK":
            print(f"Download rejected: {response.get('error', 'unknown error')}")
            return False
        payload = response.get("payload") or {}
        size = payload.get("size")
        if not isinstance(size, int):
            print("Download failed: missing size")
            return False
        destination = unique_download_path(download_dir, filename)

        # receive_to_file(sock, destination, size)

        # Added temp file handling to avoid leaving partial files on failure
        tmp_path = destination.with_suffix(".tmp")
        try:
            receive_to_file(sock, tmp_path, size)
            tmp_path.rename(destination)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        print(f"Downloaded to {destination}")
        return True


def handle_download(conn, shared_dir):
    with conn:
        try:
            request = recv_json(conn)
        except Exception:
            return
        if request.get("type") != "DOWNLOAD_REQUEST":
            send_json(conn, make_response(request.get("request_id"), "ERROR", error="bad request"))
            return
        payload = request.get("payload") or {}
        filename = payload.get("filename")
        file_path = get_file_path(shared_dir, filename)
        if not file_path:
            send_json(conn, make_response(request.get("request_id"), "ERROR", error="file not found"))
            return
        size = file_path.stat().st_size
        response = make_response(request.get("request_id"), "OK", {"filename": filename, "size": size})
        send_json(conn, response)
        with open(file_path, "rb") as handle:
            while True:
                chunk = handle.read(CHUNK_SIZE)
                if not chunk:
                    break
                conn.sendall(chunk)


def file_server_loop(server_sock, shared_dir, stop_event):
    server_sock.listen()
    server_sock.settimeout(1.0)
    while not stop_event.is_set():
        try:
            conn, _addr = server_sock.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        threading.Thread(target=handle_download, args=(conn, shared_dir), daemon=True).start()
    server_sock.close()


def start_file_server(shared_dir, listen_port, stop_event):
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("0.0.0.0", listen_port))
    actual_port = server_sock.getsockname()[1]
    thread = threading.Thread(
        target=file_server_loop, args=(server_sock, shared_dir, stop_event), daemon=True
    )
    thread.start()
    return actual_port, thread


def print_results(results):
    if not results:
        print("No matches found.")
        return
    for idx, entry in enumerate(results, start=1):
        size = format_size(entry["size"])
        print(f"{idx}. {entry['filename']} - {size} @ {entry['ip']}:{entry['port']}")


def main():
    server_host = input("Index server host [127.0.0.1]: ").strip() or "127.0.0.1"
    server_port = prompt_int("Index server port [9000]: ", 9000)
    listen_port = prompt_int("Peer listen port [0 for auto]: ", 0)
    shared_dir = input("Shared folder path [.] : ").strip() or "."
    download_dir = input("Download folder [downloads]: ").strip() or "downloads"

    stop_event = threading.Event()
    actual_port, server_thread = start_file_server(shared_dir, listen_port, stop_event)

    try:
        response, files = register_with_server(server_host, server_port, actual_port, shared_dir)
        if response.get("status") != "OK":
            print(f"Registration failed: {response.get('error', 'unknown error')}")
            return
        print(f"Registered {len(files)} files. Peer listening on port {actual_port}.")
    except Exception as exc:
        print(f"Registration failed: {exc}")
        return

    heartbeat_thread = threading.Thread(
        target=heartbeat_loop, args=(server_host, server_port, actual_port, stop_event), daemon=True
    )
    heartbeat_thread.start()

    last_results = []
    while True:
        print("\nMenu")
        print("1. Refresh share list")
        print("2. Search for a file")
        print("3. Download from peer")
        print("4. List shared files")
        print("5. Exit")
        choice = input("Select: ").strip()

        if choice == "1":
            try:
                response, files = register_with_server(server_host, server_port, actual_port, shared_dir)
                if response.get("status") == "OK":
                    print(f"Updated share list ({len(files)} files).")
                else:
                    print(f"Update failed: {response.get('error', 'unknown error')}")
            except Exception as exc:
                print(f"Update failed: {exc}")

        elif choice == "2":
            query = input("Filename to search: ").strip()
            if not query:
                continue
            try:
                last_results = search_server(server_host, server_port, query)
                print_results(last_results)
            except Exception as exc:
                print(f"Search failed: {exc}")

        elif choice == "3":
            if not last_results:
                print("No cached results. Search first.")
                continue
            selection = prompt_int("Select result number: ", 0)
            if selection < 1 or selection > len(last_results):
                print("Invalid selection.")
                continue
            peer = last_results[selection - 1]
            filename = peer["filename"]
            try:
                download_from_peer(peer, filename, download_dir)
            except Exception as exc:
                print(f"Download failed: {exc}")

        elif choice == "4":
            files = list_shared_files(shared_dir)
            if not files:
                print("No shared files found.")
                continue
            for entry in files:
                print(f"- {entry['name']} ({format_size(entry['size'])})")

        elif choice == "5":
            break

        else:
            print("Unknown option.")

    stop_event.set()
    deregister(server_host, server_port, actual_port)
    server_thread.join(timeout=2)
    heartbeat_thread.join(timeout=2)


if __name__ == "__main__":
    main()
