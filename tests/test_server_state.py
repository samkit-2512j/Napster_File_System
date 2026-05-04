import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import server


class ServerStateTests(unittest.TestCase):
    def setUp(self):
        self.current_time = 1000.0

        def fake_time():
            return self.current_time

        self.time_patch = patch.object(server.time, "time", side_effect=fake_time)
        self.time_patch.start()
        self.addCleanup(self.time_patch.stop)

    def test_register_peer_adds_peer_and_indexes_files(self):
        state = server.IndexState()

        peer_id = state.register_peer(
            "127.0.0.1",
            5000,
            [
                {"name": "alpha.txt", "size": 12},
                {"name": "beta.txt", "size": 24},
            ],
        )

        self.assertEqual(peer_id, "127.0.0.1:5000")
        self.assertIn(peer_id, state.peers)
        self.assertEqual(state.peers[peer_id]["files"], {"alpha.txt": 12, "beta.txt": 24})
        self.assertEqual(state.file_index["alpha.txt"][peer_id]["size"], 12)
        self.assertEqual(state.file_index["beta.txt"][peer_id]["size"], 24)

    def test_reregister_same_peer_replaces_previous_files(self):
        state = server.IndexState()

        state.register_peer("127.0.0.1", 5000, [{"name": "old.txt", "size": 1}])
        state.register_peer("127.0.0.1", 5000, [{"name": "new.txt", "size": 2}])

        self.assertNotIn("old.txt", state.file_index)
        self.assertEqual(state.peers["127.0.0.1:5000"]["files"], {"new.txt": 2})
        self.assertIn("new.txt", state.file_index)
        self.assertNotIn("127.0.0.1:5000", state.file_index.get("old.txt", {}))

    def test_search_returns_matching_results_and_empty_for_unknown(self):
        state = server.IndexState()
        state.register_peer("127.0.0.1", 5000, [{"name": "alpha.txt", "size": 12}])
        state.register_peer("127.0.0.2", 5001, [{"name": "beta.txt", "size": 24}])

        results = state.search("alp")

        self.assertEqual(
            results,
            [{"ip": "127.0.0.1", "port": 5000, "filename": "alpha.txt", "size": 12}],
        )
        self.assertEqual(state.search("missing"), [])

    def test_heartbeat_updates_known_peer_and_rejects_unknown(self):
        state = server.IndexState()
        state.register_peer("127.0.0.1", 5000, [{"name": "alpha.txt", "size": 12}])
        previous_seen = state.peers["127.0.0.1:5000"]["last_seen"]

        self.current_time = 1010.0

        self.assertTrue(state.heartbeat("127.0.0.1", 5000))
        self.assertEqual(state.peers["127.0.0.1:5000"]["last_seen"], 1010.0)
        self.assertGreater(state.peers["127.0.0.1:5000"]["last_seen"], previous_seen)
        self.assertFalse(state.heartbeat("127.0.0.1", 9999))

    def test_deregister_removes_peer_and_cleans_file_index(self):
        state = server.IndexState()
        state.register_peer("127.0.0.1", 5000, [{"name": "alpha.txt", "size": 12}])

        self.assertTrue(state.deregister("127.0.0.1", 5000))
        self.assertNotIn("127.0.0.1:5000", state.peers)
        self.assertNotIn("alpha.txt", state.file_index)
        self.assertFalse(state.deregister("127.0.0.1", 5000))

    def test_cleanup_removes_stale_peers_and_keeps_recent_peers(self):
        state = server.IndexState()
        state.register_peer("127.0.0.1", 5000, [{"name": "old.txt", "size": 1}])

        self.current_time = 1005.0
        state.register_peer("127.0.0.2", 5001, [{"name": "fresh.txt", "size": 2}])

        self.current_time = 1020.0
        stale = state.cleanup(timeout_sec=15)

        self.assertEqual(stale, ["127.0.0.1:5000"])
        self.assertNotIn("127.0.0.1:5000", state.peers)
        self.assertIn("127.0.0.2:5001", state.peers)
        self.assertNotIn("old.txt", state.file_index)
        self.assertIn("fresh.txt", state.file_index)

    def test_file_index_entry_removed_when_last_peer_is_deregistered(self):
        state = server.IndexState()
        state.register_peer("127.0.0.1", 5000, [{"name": "shared.txt", "size": 10}])
        state.register_peer("127.0.0.2", 5001, [{"name": "shared.txt", "size": 10}])

        state.deregister("127.0.0.1", 5000)

        self.assertIn("shared.txt", state.file_index)
        self.assertIn("127.0.0.2:5001", state.file_index["shared.txt"])

        state.deregister("127.0.0.2", 5001)

        self.assertNotIn("shared.txt", state.file_index)


if __name__ == "__main__":
    unittest.main()