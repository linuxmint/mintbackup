"""Run the backup worker against a destination that runs out of space."""
import errno
import importlib.util
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

from gi.repository import GLib


class LimitedFile:
    def __init__(self, filename, limit, error):
        self.file = open(filename, 'wb', buffering=0)
        self.remaining = limit
        self.error = error
        self.failed = False

    def write(self, data):
        if len(data) > self.remaining and not self.failed:
            self.failed = True
            raise OSError(self.error, os.strerror(self.error))
        self.remaining -= len(data)
        return self.file.write(data)

    def tell(self):
        return self.file.tell()

    def close(self):
        self.file.close()


class FullDestinationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.import_home = tempfile.TemporaryDirectory()
        path = Path(__file__).resolve().parents[1] / 'usr/lib/linuxmint/mintbackup/mintbackup.py'
        spec = importlib.util.spec_from_file_location('mintbackup', path)
        cls.module = importlib.util.module_from_spec(spec)
        # Keep the module's default backup-directory creation inside the fixture.
        with patch.object(GLib, 'get_user_special_dir', return_value=cls.import_home.name):
            spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        cls.import_home.cleanup()

    def run_backup(self, error, limit, unreadable=False):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            home = root / 'home'
            dest = root / 'backups'
            home.mkdir()
            dest.mkdir()
            for i in range(4):
                (home / str(i)).write_bytes(b'x' * 4096)
            app = self.module.MintBackup.__new__(self.module.MintBackup)
            app.home_directory = str(home)
            app.backup_dest = str(dest)
            app.follow_links = False
            app.included_files = app.included_dirs = []
            app.excluded_files = app.excluded_dirs = []
            app.settings = Mock()
            app.settings.get_string.return_value = 'tar'
            app.errors = []
            app.set_widgets_before_backup = Mock()
            app.set_widgets_after_backup = Mock()
            app.set_progress = Mock()
            outputs = []
            real_open = tarfile.open

            def open_archive(name, **kwargs):
                output = LimitedFile(name, limit, error)
                outputs.append(output)
                return real_open(fileobj=output, **kwargs)

            real_file_open = tarfile.bltn_open

            def open_source(path, *args, **kwargs):
                if unreadable and str(path) == str(home / "0"):
                    raise PermissionError(errno.EACCES, "Permission denied", str(path))
                return real_file_open(path, *args, **kwargs)

            previous = os.getcwd()
            try:
                with patch.object(self.module.GLib, 'idle_add', side_effect=lambda f, *args: f(*args)), \
                     patch.object(self.module.tarfile, 'open', side_effect=open_archive), \
                     patch.object(tarfile, 'bltn_open', side_effect=open_source):
                    app.backup()
            finally:
                os.chdir(previous)
                for output in outputs:
                    output.close()
            if error is None:
                expected = 3 if unreadable else 4
                self.assertEqual(app.archived_files, expected)
                self.assertEqual(app.set_progress.call_count, 4)
                self.assertFalse(Path(app.temp_filename).exists())
                with real_open(app.filename) as archive:
                    self.assertEqual(len(archive.getmembers()), expected + 1)
                    self.assertEqual(archive.extractfile('1').read(), b'x' * 4096)
                self.assertEqual(len(app.errors), 2 if unreadable else 0)
                app.set_widgets_after_backup.assert_called_once()
                return
            # The write error occurs once; closing can succeed after space is freed.
            self.assertTrue(outputs[0].failed)
            self.assertFalse(app.operating)
            self.assertEqual(app.archived_files, 0)
            self.assertLessEqual(app.set_progress.call_count, 1)
            self.assertTrue(any(os.strerror(error) in str(item) for item in app.errors))
            app.set_widgets_after_backup.assert_called_once()
            self.assertTrue(Path(app.temp_filename).exists())
            self.assertFalse(Path(app.filename).exists())

    def test_successful_backup(self):
        self.run_backup(None, 100000)

    def test_unreadable_source_does_not_stop_other_files(self):
        self.run_backup(None, 100000, unreadable=True)

    def test_no_space_during_first_file(self):
        self.run_backup(errno.ENOSPC, 2048)

    def test_quota_exceeded_during_first_file(self):
        self.run_backup(errno.EDQUOT, 2048)

    def test_no_space_during_archive_initialization(self):
        self.run_backup(errno.ENOSPC, 0)


if __name__ == '__main__':
    unittest.main()
