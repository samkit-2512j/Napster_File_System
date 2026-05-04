import argparse
import ipaddress
import socket
import threading
import time

from protocol import make_response, recv_json, send_json

HEARTBEAT_TIMEOUT = 15
CLEANUP_INTERVAL = 5


class IndexState:
    def __init__(self):
        self.lock = threading.Lock()
        self.peers = {}
        self.file_index = {}

    def register_peer(self, ip, port, files, username):
        peer_id = f"{ip}:{port}"
        with self.lock:
            self._remove_peer_locked(peer_id)
            file_map = {}
            for entry in files:
                name = entry.get("name")
                size = entry.get("size")
                if not name or not isinstance(size, int):
                    continue
                file_map[name] = size
                self.file_index.setdefault(name, {})[peer_id] = {
                    "ip": ip,
                    "port": port,
                    "size": size,
                    "username": username,
                }
            self.peers[peer_id] = {
                "ip": ip,
                "port": port,
                "files": file_map,
                "username": username,
                "last_seen": time.time(),
            }
        return peer_id

    def heartbeat(self, ip, port):
        peer_id = f"{ip}:{port}"
        with self.lock:
            peer = self.peers.get(peer_id)
            if not peer:
                return False
            peer["last_seen"] = time.time()
            return True

    def deregister(self, ip, port):
        peer_id = f"{ip}:{port}"
        with self.lock:
            if peer_id not in self.peers:
                return False
            self._remove_peer_locked(peer_id)
            return True

    # def search(self, filename):
    #     with self.lock:
    #         entries = self.file_index.get(filename, {})
    #         results = []
    #         for info in entries.values():
    #             results.append(
    #                 {
    #                     "ip": info["ip"],
    #                     "port": info["port"],
    #                     "filename": filename,
    #                     "size": info["size"],
    #                 }
    #             )
    #         return results

    ## Updated with Keyword search. 
        
    def search(self, query):
        with self.lock:
            results = []
            query_lower = query.lower()
            for filename, entries in self.file_index.items():
                if filename.lower().startswith(query_lower):
                    for info in entries.values():
                        results.append({
                            "ip": info["ip"], "port": info["port"],
                            "filename": filename, "size": info["size"],
                            "username": info.get("username"),
                        })
            return results

    def list_all(self):
        with self.lock:
            results = []
            for filename, entries in self.file_index.items():
                for info in entries.values():
                    results.append({
                        "ip": info["ip"], "port": info["port"],
                        "filename": filename, "size": info["size"],
                        "username": info.get("username"),
                    })
            return results

    def cleanup(self, timeout_sec):
        cutoff = time.time() - timeout_sec
        stale = []
        with self.lock:
            for peer_id, peer in list(self.peers.items()):
                if peer["last_seen"] < cutoff:
                    stale.append(peer_id)
            for peer_id in stale:
                self._remove_peer_locked(peer_id)
        return stale

    def _remove_peer_locked(self, peer_id):
        if peer_id not in self.peers:
            return
        for filename, entries in list(self.file_index.items()):
            if peer_id in entries:
                del entries[peer_id]
                if not entries:
                    del self.file_index[filename]
        del self.peers[peer_id]


def _is_usable_ip(value):
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if ip.is_unspecified:
        return False
    return True


def _select_peer_ip(addr_ip, advertised_ip):
    candidates = []
    if advertised_ip:
        candidates.append(advertised_ip)
    candidates.append(addr_ip)
    for candidate in candidates:
        if not _is_usable_ip(candidate):
            continue
        ip = ipaddress.ip_address(candidate)
        if not ip.is_loopback:
            return candidate
    return addr_ip


def handle_client(conn, addr, state):
    with conn:
        try:
            message = recv_json(conn)
        except Exception:
            return

        msg_type = message.get("type")
        request_id = message.get("request_id")
        payload = message.get("payload") or {}

        if msg_type == "REGISTER":
            listen_port = int(payload.get("listen_port", 0))
            files = payload.get("files", [])
            advertised_ip = payload.get("listen_ip") or payload.get("advertised_ip")
            username = payload.get("username")
            if listen_port <= 0:
                send_json(conn, make_response(request_id, "ERROR", error="listen_port required"))
                return
            cleaned = []
            for entry in files:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name")
                size = entry.get("size")
                if not name or not isinstance(size, int):
                    continue
                cleaned.append({"name": name, "size": size})
            peer_ip = _select_peer_ip(addr[0], advertised_ip)
            peer_id = state.register_peer(peer_ip, listen_port, cleaned, username)
            send_json(conn, make_response(request_id, "OK", {"peer_id": peer_id}))
            return

        if msg_type == "SEARCH":
            query = payload.get("query")
            if not query:
                send_json(conn, make_response(request_id, "ERROR", error="query required"))
                return
            results = state.search(query)
            send_json(conn, make_response(request_id, "OK", {"results": results}))
            return

        if msg_type == "LIST":
            results = state.list_all()
            send_json(conn, make_response(request_id, "OK", {"results": results}))
            return

        if msg_type == "HEARTBEAT":
            listen_port = int(payload.get("listen_port", 0))
            advertised_ip = payload.get("listen_ip") or payload.get("advertised_ip")
            if listen_port <= 0:
                send_json(conn, make_response(request_id, "ERROR", error="listen_port required"))
                return
            peer_ip = _select_peer_ip(addr[0], advertised_ip)
            if state.heartbeat(peer_ip, listen_port):
                send_json(conn, make_response(request_id, "OK"))
            else:
                send_json(conn, make_response(request_id, "ERROR", error="peer not registered"))
            return

        if msg_type == "DEREGISTER":
            listen_port = int(payload.get("listen_port", 0))
            advertised_ip = payload.get("listen_ip") or payload.get("advertised_ip")
            if listen_port <= 0:
                send_json(conn, make_response(request_id, "ERROR", error="listen_port required"))
                return
            peer_ip = _select_peer_ip(addr[0], advertised_ip)
            if state.deregister(peer_ip, listen_port):
                send_json(conn, make_response(request_id, "OK"))
            else:
                send_json(conn, make_response(request_id, "ERROR", error="peer not registered"))
            return

        send_json(conn, make_response(request_id, "ERROR", error="unknown message type"))


def cleanup_loop(state, stop_event):
    while not stop_event.is_set():
        stale = state.cleanup(HEARTBEAT_TIMEOUT)
        if stale:
            print(f"Removed stale peers: {', '.join(stale)}")
        stop_event.wait(CLEANUP_INTERVAL)


def serve(host, port):
    state = IndexState()
    stop_event = threading.Event()
    cleaner = threading.Thread(target=cleanup_loop, args=(state, stop_event), daemon=True)
    cleaner.start()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((host, port))
        server_sock.listen()
        server_sock.settimeout(1.0)
        print(f"Index server listening on {host}:{port}")
        try:
            while not stop_event.is_set():
                try:
                    conn, addr = server_sock.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=handle_client, args=(conn, addr, state), daemon=True).start()
        except KeyboardInterrupt:
            print("Shutting down server...")
        finally:
            stop_event.set()
            cleaner.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description="Central index server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=9000, help="Bind port")
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
