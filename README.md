# Napster-Style P2P File Sharing

This folder contains a central index server and a dual-mode peer (client + file server).

## Requirements
- Python 3.8+

## Run
1. Start the index server:
   - `python server.py --host 0.0.0.0 --port 9000`
2. Start one or more peers:
   - `python peer.py`

## Notes
- Shared files are the top-level files in the shared folder, up to 100MB each.
- Downloads are stored in the download folder you choose (default: `downloads`).
