import socket
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import peer
import protocol
import server


class IndexServerHarness:
    def __init__(self):
        self.state = server.IndexState()
        self.stop_event = threading.Event()
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind(("127.0.0.1", 0))
        self.host, self.port = self.server_sock.getsockname()[:2]
        self.server_sock.listen()
        self.server_sock.settimeout(0.2)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                conn, addr = self.server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=server.handle_client, args=(conn, addr, self.state), daemon=True).start()
        self.server_sock.close()

    def close(self):
        self.stop_event.set()
        try:
            self.server_sock.close()
        finally:
            self.thread.join(timeout=2)


def start_peer_server(shared_dir):
    stop_event = threading.Event()
    actual_port, thread = peer.start_file_server(shared_dir, 0, stop_event)
    return actual_port, stop_event, thread


class IntegrationTests(unittest.TestCase):
    def test_full_register_search_download_flow(self):
        index_server = IndexServerHarness()
        self.addCleanup(index_server.close)

        with tempfile.TemporaryDirectory() as shared_a, tempfile.TemporaryDirectory() as shared_b, tempfile.TemporaryDirectory() as downloads:
            file_a = Path(shared_a) / "alpha.txt"
            file_b = Path(shared_b) / "beta.txt"
            file_a.write_text("alpha payload")
            file_b.write_text("beta payload")

            port_a, stop_a, thread_a = start_peer_server(shared_a)
            port_b, stop_b, thread_b = start_peer_server(shared_b)
            self.addCleanup(stop_a.set)
            self.addCleanup(stop_b.set)
            self.addCleanup(thread_a.join, 2)
            self.addCleanup(thread_b.join, 2)

            response_a, _ = peer.register_with_server(index_server.host, index_server.port, port_a, shared_a)
            response_b, _ = peer.register_with_server(index_server.host, index_server.port, port_b, shared_b)
            self.assertEqual(response_a["status"], "OK")
            self.assertEqual(response_b["status"], "OK")

            results = peer.search_server(index_server.host, index_server.port, "alpha")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["filename"], "alpha.txt")

            downloaded = peer.download_from_peer(results[0], "alpha.txt", downloads)
            self.assertTrue(downloaded)
            self.assertEqual((Path(downloads) / "alpha.txt").read_text(), "alpha payload")

    def test_peer_reregistration_updates_file_list(self):
        index_server = IndexServerHarness()
        self.addCleanup(index_server.close)

        with tempfile.TemporaryDirectory() as shared_dir:
            old_file = Path(shared_dir) / "old.txt"
            old_file.write_text("old")

            port, stop_event, thread = start_peer_server(shared_dir)
            self.addCleanup(stop_event.set)
            self.addCleanup(thread.join, 2)

            response, _ = peer.register_with_server(index_server.host, index_server.port, port, shared_dir)
            self.assertEqual(response["status"], "OK")
            self.assertEqual(peer.search_server(index_server.host, index_server.port, "old")[0]["filename"], "old.txt")

            old_file.unlink()
            new_file = Path(shared_dir) / "new.txt"
            new_file.write_text("new")

            response, _ = peer.register_with_server(index_server.host, index_server.port, port, shared_dir)
            self.assertEqual(response["status"], "OK")
            self.assertEqual(peer.search_server(index_server.host, index_server.port, "new")[0]["filename"], "new.txt")
            self.assertEqual(peer.search_server(index_server.host, index_server.port, "old"), [])

    def test_search_returns_empty_after_peer_deregisters(self):
        index_server = IndexServerHarness()
        self.addCleanup(index_server.close)

        with tempfile.TemporaryDirectory() as shared_dir:
            file_path = Path(shared_dir) / "alpha.txt"
            file_path.write_text("alpha")

            port, stop_event, thread = start_peer_server(shared_dir)
            self.addCleanup(stop_event.set)
            self.addCleanup(thread.join, 2)

            response, _ = peer.register_with_server(index_server.host, index_server.port, port, shared_dir)
            self.assertEqual(response["status"], "OK")
            self.assertEqual(peer.search_server(index_server.host, index_server.port, "alpha")[0]["filename"], "alpha.txt")

            peer.deregister(index_server.host, index_server.port, port)
            self.assertEqual(peer.search_server(index_server.host, index_server.port, "alpha"), [])

    def test_server_evicts_peer_after_timeout_cleanup(self):
        index_server = IndexServerHarness()
        self.addCleanup(index_server.close)

        with tempfile.TemporaryDirectory() as shared_dir:
            file_path = Path(shared_dir) / "stale.txt"
            file_path.write_text("stale")

            port, stop_event, thread = start_peer_server(shared_dir)
            self.addCleanup(stop_event.set)
            self.addCleanup(thread.join, 2)

            response, _ = peer.register_with_server(index_server.host, index_server.port, port, shared_dir)
            self.assertEqual(response["status"], "OK")

            peer_id = f"127.0.0.1:{port}"
            index_server.state.peers[peer_id]["last_seen"] = 0

            stale = index_server.state.cleanup(timeout_sec=1)

            self.assertIn(peer_id, stale)
            self.assertNotIn(peer_id, index_server.state.peers)
            self.assertEqual(peer.search_server(index_server.host, index_server.port, "stale"), [])

    def test_downloading_missing_file_returns_error_and_no_bytes_follow(self):
        with tempfile.TemporaryDirectory() as shared_dir:
            port, stop_event, thread = start_peer_server(shared_dir)
            self.addCleanup(stop_event.set)
            self.addCleanup(thread.join, 2)

            with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
                protocol.send_json(sock, protocol.make_request("DOWNLOAD_REQUEST", {"filename": "missing.txt"}))
                response = protocol.recv_json(sock)
                self.assertEqual(response["status"], "ERROR")
                self.assertEqual(sock.recv(1), b"")

    def test_concurrent_downloads_from_same_peer_complete_correctly(self):
        index_server = IndexServerHarness()
        self.addCleanup(index_server.close)

        with tempfile.TemporaryDirectory() as shared_dir, tempfile.TemporaryDirectory() as download_a, tempfile.TemporaryDirectory() as download_b:
            file_path = Path(shared_dir) / "shared.bin"
            payload = b"z" * (256 * 1024)
            file_path.write_bytes(payload)

            port, stop_event, thread = start_peer_server(shared_dir)
            self.addCleanup(stop_event.set)
            self.addCleanup(thread.join, 2)

            response, _ = peer.register_with_server(index_server.host, index_server.port, port, shared_dir)
            self.assertEqual(response["status"], "OK")

            results = peer.search_server(index_server.host, index_server.port, "shared")
            self.assertEqual(len(results), 1)

            errors = []

            def download_to(target_dir):
                try:
                    ok = peer.download_from_peer(results[0], "shared.bin", target_dir)
                    if not ok:
                        errors.append("download failed")
                except Exception as exc:
                    errors.append(str(exc))

            thread_a = threading.Thread(target=download_to, args=(download_a,))
            thread_b = threading.Thread(target=download_to, args=(download_b,))
            thread_a.start()
            thread_b.start()
            thread_a.join(timeout=5)
            thread_b.join(timeout=5)

            self.assertFalse(errors)
            self.assertEqual((Path(download_a) / "shared.bin").read_bytes(), payload)
            self.assertEqual((Path(download_b) / "shared.bin").read_bytes(), payload)

    def test_unique_download_path_does_not_clobber_existing_files(self):
        with tempfile.TemporaryDirectory() as download_dir:
            existing = Path(download_dir) / "example.txt"
            existing.write_text("original")

            candidate = peer.unique_download_path(download_dir, "example.txt")

            self.assertEqual(candidate.name, "example_1.txt")
            self.assertEqual(existing.read_text(), "original")

    def test_server_handles_malformed_json_without_responding(self):
        server_sock, client_sock = socket.socketpair()
        self.addCleanup(server_sock.close)
        self.addCleanup(client_sock.close)

        state = server.IndexState()
        thread = threading.Thread(
            target=server.handle_client,
            args=(server_sock, ("127.0.0.1", 5000), state),
            daemon=True,
        )
        thread.start()

        bad_payload = b'{"type":"REGISTER",'
        client_sock.sendall(struct.pack(protocol.HEADER_FORMAT, len(bad_payload)))
        client_sock.sendall(bad_payload)
        client_sock.shutdown(socket.SHUT_WR)

        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        client_sock.settimeout(1)
        self.assertEqual(client_sock.recv(1), b"")


if __name__ == "__main__":
    unittest.main()