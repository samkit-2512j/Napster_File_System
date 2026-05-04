import ipaddress
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


def _is_loopback(value):
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return True


def detect_advertised_ip(server_host):
    candidates = []

    def add_candidate(value):
        if value and value not in candidates:
            candidates.append(value)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((server_host, 1))
            add_candidate(sock.getsockname()[0])
    except OSError:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            add_candidate(sock.getsockname()[0])
    except OSError:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add_candidate(info[4][0])
    except OSError:
        pass

    for candidate in candidates:
        if not _is_loopback(candidate):
            return candidate
    return candidates[0] if candidates else "127.0.0.1"


def register_with_server(host, port, listen_port, shared_dir, advertised_ip, username):
    files = list_shared_files(shared_dir)
    message = make_request(
        "REGISTER",
        {
            "listen_port": listen_port,
            "listen_ip": advertised_ip,
            "files": files,
            "username": username,
        },
    )
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


def list_all_files(host, port):
    message = make_request("LIST")
    response = send_server_request(host, port, message)
    if response.get("status") != "OK":
        print(f"List failed: {response.get('error', 'unknown error')}")
        return []
    payload = response.get("payload") or {}
    return payload.get("results", [])


def send_heartbeat(host, port, listen_port, advertised_ip):
    message = make_request(
        "HEARTBEAT",
        {"listen_port": listen_port, "listen_ip": advertised_ip},
    )
    response = send_server_request(host, port, message)
    return response.get("status") == "OK"


def deregister(host, port, listen_port, advertised_ip):
    message = make_request(
        "DEREGISTER",
        {"listen_port": listen_port, "listen_ip": advertised_ip},
    )
    try:
        send_server_request(host, port, message)
    except Exception:
        return


def heartbeat_loop(host, port, listen_port, advertised_ip, stop_event):
    failures = 0
    while not stop_event.is_set():
        try:
            ok = send_heartbeat(host, port, listen_port, advertised_ip)
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


def build_catalog(results):
    catalog = {}
    for entry in results:
        filename = entry.get("filename")
        size = entry.get("size")
        if not filename or not isinstance(size, int):
            continue
        record = catalog.setdefault(
            filename,
            {"filename": filename, "size": size, "peers": []},
        )
        record["peers"].append(
            {
                "ip": entry.get("ip"),
                "port": entry.get("port"),
                "size": size,
                "username": entry.get("username"),
            }
        )
    return sorted(catalog.values(), key=lambda item: item["filename"].lower())


def print_catalog(catalog):
    for idx, entry in enumerate(catalog, start=1):
        size = format_size(entry["size"])
        peer_count = len(entry["peers"])
        suffix = f" ({peer_count} peers)" if peer_count > 1 else ""
        print(f"{idx}. {entry['filename']} - {size}{suffix}")


def filter_catalog(catalog, query):
    query_lower = query.lower()
    return [entry for entry in catalog if entry["filename"].lower().startswith(query_lower)]


def main():
    server_host = input("Index server host [127.0.0.1]: ").strip() or "127.0.0.1"
    server_port = prompt_int("Index server port [9000]: ", 9000)
    username = input("Username: ").strip()
    listen_port = prompt_int("Peer listen port [0 for auto]: ", 0)
    shared_dir = input("Shared folder path [.] : ").strip() or "."
    download_dir = input("Download folder [downloads]: ").strip() or "downloads"

    stop_event = threading.Event()
    actual_port, server_thread = start_file_server(shared_dir, listen_port, stop_event)
    advertised_ip = detect_advertised_ip(server_host)

    try:
        response, files = register_with_server(
            server_host, server_port, actual_port, shared_dir, advertised_ip, username
        )
        if response.get("status") != "OK":
            print(f"Registration failed: {response.get('error', 'unknown error')}")
            return
        print(f"Registered {len(files)} files. Peer listening on port {actual_port}.")
    except Exception as exc:
        print(f"Registration failed: {exc}")
        return

    heartbeat_thread = threading.Thread(
        target=heartbeat_loop,
        args=(server_host, server_port, actual_port, advertised_ip, stop_event),
        daemon=True,
    )
    heartbeat_thread.start()

    while True:
        print("\nMenu")
        print("1. Refresh share list")
        print("2. Download")
        print("3. List shared files")
        print("4. Exit")
        choice = input("Select: ").strip()

        if choice == "1":
            try:
                response, files = register_with_server(
                    server_host, server_port, actual_port, shared_dir, advertised_ip, username
                )
                if response.get("status") == "OK":
                    print(f"Updated share list ({len(files)} files).")
                else:
                    print(f"Update failed: {response.get('error', 'unknown error')}")
            except Exception as exc:
                print(f"Update failed: {exc}")

        elif choice == "2":
            try:
                results = list_all_files(server_host, server_port)
            except Exception as exc:
                print(f"List failed: {exc}")
                continue
            if not results:
                print("No files available.")
                continue
            catalog = build_catalog(results)
            print("\nAvailable files:")
            print_catalog(catalog)

            query = input("Filter by name (leave blank to skip): ").strip()
            if query:
                catalog = filter_catalog(catalog, query)
                if not catalog:
                    print("No matches found.")
                    continue
                print("\nMatches:")
                print_catalog(catalog)

            selection = prompt_int("Select file number: ", 0)
            if selection < 1 or selection > len(catalog):
                print("Invalid selection.")
                continue

            entry = catalog[selection - 1]
            filename = entry["filename"]
            peers = entry["peers"]
            if len(peers) == 1:
                try:
                    download_from_peer(peers[0], filename, download_dir)
                except Exception as exc:
                    print(f"Download failed: {exc}")
                continue

            print("\nFile is available on multiple peers:")
            for idx, peer in enumerate(peers, start=1):
                label = f"{peer['ip']}:{peer['port']}"
                if peer.get("username"):
                    label = f"{label} ({peer['username']})"
                print(f"{idx}. {label}")
            peer_choice = prompt_int("Select peer number: ", 0)
            if peer_choice < 1 or peer_choice > len(peers):
                print("Invalid selection.")
                continue
            try:
                download_from_peer(peers[peer_choice - 1], filename, download_dir)
            except Exception as exc:
                print(f"Download failed: {exc}")

        elif choice == "3":
            files = list_shared_files(shared_dir)
            if not files:
                print("No shared files found.")
                continue
            for entry in files:
                print(f"- {entry['name']} ({format_size(entry['size'])})")

        elif choice == "4":
            break

        else:
            print("Unknown option.")

    stop_event.set()
    deregister(server_host, server_port, actual_port, advertised_ip)
    server_thread.join(timeout=2)
    heartbeat_thread.join(timeout=2)


if __name__ == "__main__":
    main()
