# Distributed File Sharing System - Napster-Style Implementation
## Project Proposal

**Student Name:** [Your Name]
**Course:** Distributed Systems
**Duration:** 1 Month
**Date:** March 21, 2026

---

## 1. Problem Statement

Traditional file sharing systems rely on centralized servers that store and distribute files, creating bottlenecks and single points of failure. This project implements a Napster-style distributed file sharing system that enables peer-to-peer (P2P) file transfer while maintaining a centralized indexing server for efficient file discovery. The system allows users to share files directly from their computers, reducing server load and enabling scalable file distribution across the network.

## 2. System Architecture

The system consists of two main components:

### 2.1 Central Index Server
- Maintains a registry of all connected peers and their shared files
- Provides search functionality to locate files across the network
- Stores metadata: filename, file size, peer IP address, and port
- Does NOT store actual file content
- Handles peer registration and deregistration

### 2.2 Peer Nodes (Clients)
Each peer operates in dual mode:
- **Client Mode:** Search for files and initiate downloads
- **Server Mode:** Share files and respond to download requests from other peers

## 3. Core Features

### 3.1 Registration
- Peers register with the central server upon connection
- Share a list of files available for download
- Server indexes files with peer location information

### 3.2 Search
- Peers query the central server with filename or keywords
- Server returns a list of peers hosting the requested file
- Display file metadata (size, availability) to the user

### 3.3 Download
- Direct peer-to-peer file transfer
- User selects from available peers hosting the file
- File transfer occurs without server involvement
- Basic error handling for connection failures

### 3.4 Heartbeat & Crash Detection
- Periodic heartbeat messages between each peer and the central server
- Server tracks last-seen timestamp for every registered peer
- If heartbeat timeout occurs, server marks peer as disconnected/crashed
- Server removes stale peer entries from file index automatically
- Other peers receive updated search results without crashed peers

## 4. Technology Stack

### 4.1 Programming Language
**Python 3.8+** - Selected for the following reasons:
- Built-in socket programming support for network communication
- Threading library for handling concurrent connections
- Rich standard library reducing external dependencies
- Cross-platform compatibility
- Rapid development suitable for 1-month timeline

### 4.2 Key Libraries
- `socket`: TCP/IP network communication
- `threading`: Concurrent client handling
- `json`: Data serialization for protocol messages
- `hashlib`: File integrity verification (optional)
- `os`/`pathlib`: File system operations

### 4.3 Communication Protocol
- **TCP sockets** for reliable file transfer
- **Custom JSON-based protocol** for command messages
- Message types: REGISTER, SEARCH, DOWNLOAD_REQUEST, FILE_TRANSFER, HEARTBEAT, HEARTBEAT_ACK

## 5. Implementation Plan

### Week 1: Foundation
- Design protocol specification and message formats
- Implement basic central server with peer registration
- Create peer node with server connection capability
- Unit tests for core components

### Week 2: Core Features
- Implement file indexing and search functionality
- Build peer-to-peer file transfer mechanism
- Add concurrent connection handling
- Integration testing

### Week 3: Enhancement & Reliability
- Error handling and connection recovery
- File integrity verification
- Graceful peer disconnection and crash timeout handling
- Performance testing with multiple peers

### Week 4: Testing & Documentation
- End-to-end system testing
- Bug fixes and optimization
- User documentation and setup guide
- Final presentation preparation

## 6. Deliverables

### 6.1 Source Code
1. **Index Server** (`server.py`)
   - Peer registration and deregistration
   - File index management
   - Search query processing

2. **Peer Client** (`peer.py`)
   - File sharing server component
   - Search and download client component
   - User interface (CLI-based)

3. **Utilities** (`protocol.py`, `file_handler.py`)
   - Protocol message handlers
   - File transfer utilities

### 6.2 Documentation
- `README.md`: Setup and usage instructions
- `PROTOCOL.md`: Communication protocol specification
- Code comments and docstrings

### 6.3 Demo & Testing
- Test suite with sample files
- Demo script showing all three core features
- Multi-peer testing scenario (minimum 3 peers)

## 7. System Constraints & Assumptions

### 7.1 Scope Limitations (for 1-month timeline)
- Text and small binary file support (< 100MB)
- No authentication or encryption
- Basic CLI interface (no GUI)
- Single central server (no server replication)
- Files identified by exact filename matching

### 7.2 Assumptions
- Peers operate on a local network or have accessible IP addresses
- Shared files remain available during peer connection
- Files are atomic: only files smaller than 100MB are supported, files are not chunked for download, and partial downloads are not supported; failed downloads must be restarted
- Peers are cooperative (no malicious behavior handling)
- Central server is always available

## 8. Success Criteria

The project will be considered successful when:
1. Multiple peers can register and share files with the central server
2. Users can search for files and receive accurate peer lists
3. Direct peer-to-peer file transfer works reliably
4. System handles at least 5 concurrent peers
5. Server detects crashed peers via heartbeat timeout and removes stale index entries
6. All three core features (Register, Search, Download) are fully functional
7. Complete documentation is provided

## 9. Testing Strategy

- **Unit Testing:** Individual components (file handler, protocol parser)
- **Integration Testing:** Server-peer communication
- **System Testing:** Complete workflow with multiple peers
- **Performance Testing:** Concurrent downloads and server load

## 10. Risk Mitigation

| Risk | Mitigation Strategy |
|------|---------------------|
| Network complexity | Use localhost testing initially, then LAN |
| Concurrent access issues | Implement proper thread synchronization |
| File transfer failures | Add retry mechanism and error reporting |
| Silent peer crashes | Heartbeat timeout and automatic peer cleanup |
| Time constraints | Focus on core features first, enhancements later |

---

## References
- Original Paper: [P2P Design Document](https://www.scribd.com/document/456414891/P2P-Design-Document)
- Python Socket Programming Documentation
- Napster Architecture Overview

---

**Signature:** ___________________
**Date:** March 21, 2026
