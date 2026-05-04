from pathlib import Path

MAX_FILE_SIZE = 100 * 1024 * 1024


def list_shared_files(shared_dir):
    shared_path = Path(shared_dir).resolve()
    if not shared_path.exists() or not shared_path.is_dir():
        return []
    files = []
    for entry in shared_path.iterdir():
        if entry.is_file():
            size = entry.stat().st_size
            if size <= MAX_FILE_SIZE:
                files.append({"name": entry.name, "size": size})
    return files


def get_file_path(shared_dir, filename):
    if not filename or "/" in filename or "\\" in filename:
        return None
    shared_path = Path(shared_dir).resolve()
    file_path = (shared_path / filename).resolve()
    if file_path.parent != shared_path:
        return None
    if not file_path.exists() or not file_path.is_file():
        return None
    if file_path.stat().st_size > MAX_FILE_SIZE:
        return None
    return file_path
