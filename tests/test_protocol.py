import socket
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import protocol


class ProtocolTests(unittest.TestCase):
    def test_send_json_recv_json_round_trip(self):
        sender, receiver = socket.socketpair()
        self.addCleanup(sender.close)
        self.addCleanup(receiver.close)

        message = {"type": "PING", "request_id": "123", "payload": {"value": 7}}
        protocol.send_json(sender, message)

        received = protocol.recv_json(receiver)
        self.assertEqual(received, message)

    def test_recv_json_raises_on_truncated_data(self):
        sender, receiver = socket.socketpair()
        self.addCleanup(sender.close)
        self.addCleanup(receiver.close)

        payload = b'{"type":"PING"'
        sender.sendall(struct.pack(protocol.HEADER_FORMAT, len(payload) + 5))
        sender.sendall(payload)
        sender.close()

        with self.assertRaises(ConnectionError):
            protocol.recv_json(receiver)

    def test_recv_json_raises_when_message_is_too_large(self):
        sender, receiver = socket.socketpair()
        self.addCleanup(sender.close)
        self.addCleanup(receiver.close)

        sender.sendall(struct.pack(protocol.HEADER_FORMAT, protocol.MAX_MESSAGE_SIZE + 1))
        sender.close()

        with self.assertRaises(ValueError):
            protocol.recv_json(receiver)

    def test_make_request_generates_unique_request_ids(self):
        with patch("protocol.uuid.uuid4", side_effect=["first", "second"]):
            first = protocol.make_request("PING")
            second = protocol.make_request("PING")

        self.assertEqual(first["request_id"], "first")
        self.assertEqual(second["request_id"], "second")
        self.assertNotEqual(first["request_id"], second["request_id"])

    def test_make_response_includes_error_only_when_provided(self):
        response = protocol.make_response("abc", "ERROR", error="bad request")
        self.assertEqual(response["error"], "bad request")

        ok_response = protocol.make_response("abc", "OK")
        self.assertNotIn("error", ok_response)


if __name__ == "__main__":
    unittest.main()