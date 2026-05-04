import json
import struct
import uuid

HEADER_FORMAT = "!I"
HEADER_SIZE = 4
MAX_MESSAGE_SIZE = 2 * 1024 * 1024


def make_request(msg_type, payload=None, request_id=None):
    return {
        "type": msg_type,
        "request_id": request_id or str(uuid.uuid4()),
        "payload": payload or {},
    }


def make_response(request_id, status, payload=None, error=None):
    message = {"type": "RESPONSE", "request_id": request_id, "status": status}
    if payload is not None:
        message["payload"] = payload
    if error is not None:
        message["error"] = error
    return message


def send_json(sock, message):
    data = json.dumps(message, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if len(data) > MAX_MESSAGE_SIZE:
        raise ValueError("Message too large")
    header = struct.pack(HEADER_FORMAT, len(data))
    sock.sendall(header + data)


def recv_exactly(sock, num_bytes):
    chunks = []
    remaining = num_bytes
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("Socket closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def recv_json(sock):
    header = recv_exactly(sock, HEADER_SIZE)
    (length,) = struct.unpack(HEADER_FORMAT, header)
    if length > MAX_MESSAGE_SIZE:
        raise ValueError("Message too large")
    data = recv_exactly(sock, length)
    return json.loads(data.decode("utf-8"))
