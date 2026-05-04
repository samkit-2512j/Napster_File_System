## server.py

- `handle_client` only reads one message per connection This is fine given your protocol (one request per connection), but it means a new TCP connection is opened for every heartbeat every 5 seconds. For this project this is acceptable, but a persistent connection with multiplexed requests would be more efficient at scale.

## Tests:

### Unit Tests (`test_protocol.py`)

- `send_json` / `recv_json` round-trip with a socket pair (`socket.socketpair()`)
- `recv_json` raises on truncated data
- `recv_json` raises when `length > MAX_MESSAGE_SIZE`
- `make_request` generates unique `request_id` values
- `make_response` includes `error` only when provided

### Unit Tests (`test_file_handler.py`)

- `list_shared_files` returns correct name/size for files in a temp dir
- `list_shared_files` excludes files over 100MB (mock `stat()`)
- `get_file_path` returns None for path traversal attempts: `"../secret"`, `"a/b"`, `"a\\b"`
- `get_file_path` returns `None` for nonexistent files
- `get_file_path` returns correct path for a valid file

### Unit Tests (test_server_state.py)

- `register_peer` adds peer and indexes its files
- Re-registering the same peer replaces its old file list (no duplicates)
- `search` returns correct results for an indexed filename
- `search` returns empty list for unknown filename
- `heartbeat` returns `True` for a known peer, `False` for unknown
- `deregister` removes peer and cleans up file index
- `cleanup` removes peers whose `last_seen` is past the timeout
- `cleanup` does not remove recently seen peers
- File index entry is removed when the last peer sharing it is deregistered

### Integration Tests (test_integration.py)

- Full register → search → download flow between two in-process peers
- Peer re-registration updates the file list correctly
- Server returns empty search results after a peer deregisters
- Server evicts a peer after heartbeat timeout (use a very short timeout in the test)
- Downloading a nonexistent file returns an ERROR response, no bytes sent
- Concurrent downloads from the same peer complete correctly
- `unique_download_path` doesn't clobber existing files

### Edge Case / Robustness Tests

- `REGISTER` with `listen_port: 0` returns ERROR
- `REGISTER` with malformed file entries (missing `name`, non-int `size`) are silently skipped
- `SEARCH` with empty query returns ERROR
- `DOWNLOAD_REQUEST` with a path traversal filename (`"../etc/passwd"`) is rejected
- Connection dropped mid-download leaves no partial file (after the `.tmp` fix above)
- Server handles a client that connects and sends nothing (timeout/close)
- Server handles a client that sends malformed JSON
