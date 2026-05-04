# Tests

This directory contains unit and integration tests for the Napster-style P2P file sharing project.

## `test_protocol.py`

Validates the JSON framing helpers in `protocol.py`.

### `test_send_json_recv_json_round_trip`
Creates a connected socket pair and sends a JSON message through one end with `send_json`, then reads it back from the other end with `recv_json`. Verifies that the decoded message matches the original payload. This validates the full length-prefix framing and JSON encode/decode cycle in one shot.

### `test_recv_json_raises_on_truncated_data`
Sends a header that claims the body will be `N + 5` bytes long, but only sends `N` bytes before closing the socket. Expects `recv_json` to raise `ConnectionError` because `recv_exactly` cannot fill the promised length. This catches mid-message connection drops.

### `test_recv_json_raises_when_message_is_too_large`
Sends only a header with a length value greater than `MAX_MESSAGE_SIZE`, then closes the socket. Expects `recv_json` to raise `ValueError` before reading the body. This verifies that the size guard triggers early.

### `test_make_request_generates_unique_request_ids`
Patches `uuid.uuid4` to return controlled values (`"first"`, `"second"`) and verifies that two requests receive different `request_id` values. This tests the uniqueness contract rather than UUID randomness itself.

### `test_make_response_includes_error_only_when_provided`
Calls `make_response` with an error string and checks that the `error` key is present, then calls it without an error and checks that the key is absent entirely. This prevents bugs where a response contains `"error": null` instead of omitting the field.

## `test_file_handler.py`

Validates file listing and path resolution logic in `file_handler.py`.

### `test_list_shared_files_returns_name_and_size`
Creates a temporary directory with one file containing `hello` and asserts that `list_shared_files` returns exactly `[{"name": "example.txt", "size": 5}]`. This is the happy-path test for shared file enumeration.

### `test_list_shared_files_excludes_files_over_limit`
Writes a small real file, but patches `Path.stat` so the file reports a size larger than `MAX_FILE_SIZE`. Verifies that the function returns an empty list. The patched stat result needs `st_mode=stat.S_IFREG` so it still looks like a real regular-file stat result.

### `test_get_file_path_rejects_path_traversal_attempts`
Runs `"../secret"`, `"a/b"`, and `"a\\b"` through `get_file_path` using `subTest` so each case is reported separately on failure. All should return `None`. This is the security test that prevents escaping the shared directory.

### `test_get_file_path_returns_none_for_nonexistent_file`
Calls `get_file_path` with a filename that does not exist in the temporary directory and asserts that `None` is returned.

### `test_get_file_path_returns_valid_path`
Creates a real file and verifies that `get_file_path` returns its resolved `Path` object. This covers the happy path for valid file lookup.

## `test_server_state.py`

Exercises the in-memory index server state and its cleanup behavior in `server.py`.

### `setUp` and time patching
Every test in the class patches `server.time.time` with a function that returns `self.current_time`, which starts at `1000.0`. That gives each test full control over time without sleeping, making timeout and cleanup behavior deterministic.

### `test_register_peer_adds_peer_and_indexes_files`
Registers one peer with two files and asserts that the returned peer ID is `"ip:port"`, that the peer appears in `state.peers` with the correct file map, and that both filenames appear in `state.file_index` with the expected sizes.

### `test_reregister_same_peer_replaces_previous_files`
Registers the same peer twice with different file lists. Verifies that the old file is removed from `file_index`, the new file is present, and `state.peers` reflects only the latest list. This tests the replace-not-accumulate contract of re-registration.

### `test_search_returns_matching_results_and_empty_for_unknown`
Registers two peers with different files, then searches for `"alp"` using substring matching. Verifies that only the matching result is returned and that an unknown query returns an empty list.

### `test_heartbeat_updates_known_peer_and_rejects_unknown`
Registers a peer at time `1000`, advances the clock to `1010`, and sends a heartbeat. Confirms that `last_seen` is updated to `1010`. Also verifies that heartbeating an unknown peer returns `False`.

### `test_deregister_removes_peer_and_cleans_file_index`
Registers a peer, deregisters it, and checks that the peer is removed from `state.peers` and its file entries disappear from `state.file_index`. It also calls `deregister` a second time and verifies that it returns `False`, confirming idempotent behavior.

### `test_cleanup_removes_stale_peers_and_keeps_recent_peers`
Registers peer A at `t=1000` and peer B at `t=1005`. Advances time to `t=1020` and calls `cleanup(timeout_sec=15)`. Peer A is stale because `1000 < 1005`, while peer B survives because the cleanup check is strictly less than the cutoff.

### `test_file_index_entry_removed_when_last_peer_is_deregistered`
Registers two peers that share the same filename. Deregisters the first and verifies that the filename stays indexed because the second peer still has it. Deregisters the second and verifies that the filename is removed completely. This tests reference-style cleanup in `_remove_peer_locked`.

## `test_integration.py`

Contains end-to-end tests that spin up real sockets and exercise the full flow between peers and the index server.

### Harness
The `IndexServerHarness` starts a real TCP server on a random port in a background thread, backed by a real `IndexState`. This avoids port conflicts while still testing actual network behavior.

### `test_full_register_search_download_flow`
Creates two peers with separate shared directories, registers both with the index server, searches for a file from peer A, and then downloads it over a real socket connection. Verifies the downloaded file contents on disk. This is the main smoke test for the whole system.

### `test_peer_reregistration_updates_file_list`
Registers a peer, searches for its file, deletes the file from disk and adds a new one, then re-registers. Verifies that the old file disappears from search results and the new file appears. This matches the user-facing refresh-share workflow.

### `test_search_returns_empty_after_peer_deregisters`
Registers a peer, confirms its file is searchable, deregisters it, and then confirms the result set is empty. This verifies clean removal from the index.

### `test_server_evicts_peer_after_timeout_cleanup`
Registers a peer, then directly sets `state.peers[peer_id]["last_seen"] = 0` to simulate an ancient peer. Calls `cleanup(timeout_sec=1)` and verifies that the peer is returned as stale, removed from `state.peers`, and no longer searchable.

### `test_downloading_missing_file_returns_error_and_no_bytes_follow`
Opens a raw socket to a peer file server, sends a `DOWNLOAD_REQUEST` for a missing file, and verifies that the JSON response is `ERROR`. Then checks that `sock.recv(1)` returns `b""`, confirming that the server closes the connection cleanly without sending stray bytes.

### `test_concurrent_downloads_from_same_peer_complete_correctly`
Writes a 256 KB binary file, starts two download threads at the same time, and waits for both to finish. Asserts that no errors occur and that both downloaded files contain the correct content. This stress-tests per-connection threading in the file server.

### `test_unique_download_path_does_not_clobber_existing_files`
Creates `example.txt`, then calls `unique_download_path` with the same name. Verifies that the returned path is `example_1.txt` and that the original file remains untouched.

### `test_server_handles_malformed_json_without_responding`
Sends a valid-length header with a truncated or invalid JSON body, then shuts down the write end. Verifies that `handle_client` exits cleanly and that the client reads `b""`, meaning the server closed the connection without sending a response. This tests graceful error swallowing for malformed input.

## Notes

- The unit tests cover framing, file safety, and server state transitions.
- The integration tests cover registration, search, downloads, deregistration, cleanup, malformed input, and concurrent transfers.
- Together they exercise the project’s core behavior end to end.