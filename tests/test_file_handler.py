import sys
import tempfile
import unittest
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import file_handler


class FileHandlerTests(unittest.TestCase):
    def test_list_shared_files_returns_name_and_size(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.txt"
            file_path.write_text("hello")

            result = file_handler.list_shared_files(temp_dir)

            self.assertEqual(result, [{"name": "example.txt", "size": 5}])

    def test_list_shared_files_excludes_files_over_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "large.bin"
            file_path.write_text("x")

            original_stat = Path.stat

            def fake_stat(self):
                if self == file_path:
                    return SimpleNamespace(
                        st_size=file_handler.MAX_FILE_SIZE + 1,
                        st_mode=stat.S_IFREG,
                    )
                return original_stat(self)

            with patch.object(file_handler.Path, "stat", new=fake_stat):
                result = file_handler.list_shared_files(temp_dir)

            self.assertEqual(result, [])

    def test_get_file_path_rejects_path_traversal_attempts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for filename in ["../secret", "a/b", "a\\b"]:
                with self.subTest(filename=filename):
                    self.assertIsNone(file_handler.get_file_path(temp_dir, filename))

    def test_get_file_path_returns_none_for_nonexistent_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertIsNone(file_handler.get_file_path(temp_dir, "missing.txt"))

    def test_get_file_path_returns_valid_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "present.txt"
            file_path.write_text("content")

            result = file_handler.get_file_path(temp_dir, "present.txt")

            self.assertEqual(result, file_path.resolve())


if __name__ == "__main__":
    unittest.main()