# Protocol Specification

## Transport
- TCP sockets.
- Control messages use length-prefixed JSON: 4-byte big-endian length header followed by UTF-8 JSON.

## Message Envelope
Requests:
- `type`: message type string
- `request_id`: unique request id string
- `payload`: object

Responses:
- `type`: `RESPONSE`
- `request_id`: mirrors the request
- `status`: `OK` or `ERROR`
- `payload`: object (optional)
- `error`: error string (optional)

## Message Types
`REGISTER`
- Payload: `{"listen_port": int, "files": [{"name": str, "size": int}]}`
- Response: `OK` with `{"peer_id": str}`

`SEARCH`
- Payload: `{"query": str}`
- Response: `OK` with `{"results": [{"ip": str, "port": int, "filename": str, "size": int}]}`

`HEARTBEAT`
- Payload: `{"listen_port": int}`
- Response: `OK` or `ERROR`

`DEREGISTER`
- Payload: `{"listen_port": int}`
- Response: `OK` or `ERROR`

`DOWNLOAD_REQUEST` (peer-to-peer)
- Payload: `{"filename": str}`

## Download Flow
1. Downloader opens a TCP connection to the peer.
2. Downloader sends `DOWNLOAD_REQUEST`.
3. Peer responds with `RESPONSE` status `OK` and payload `{"filename": str, "size": int}`.
4. Peer streams exactly `size` raw bytes immediately after the response.
5. If the response status is `ERROR`, no file bytes are sent.
