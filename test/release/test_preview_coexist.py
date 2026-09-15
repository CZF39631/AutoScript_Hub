"""独立 unittest；不启动 EXE、不加载主树 pytest/conftest。"""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / 'release/windows/smoke_preview_coexist.py'
spec = importlib.util.spec_from_file_location('preview_coexist', SOURCE)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class PreviewCoexistTests(unittest.TestCase):
    def test_frozen_default_path_not_overridden(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(smoke.os.environ, {'AUTOSCRIPT_CLIENT_DATA_DIR': 'forbidden',
                    'AUTOSCRIPT_INSTALL_FLAVOR': 'stable', 'HTTP_PROXY': 'forbidden',
                    'BACKEND_URL': 'forbidden'}, clear=False):
                env = smoke.frozen_environment(root, 'http://127.0.0.1:12345')
            self.assertNotIn('AUTOSCRIPT_CLIENT_DATA_DIR', env)
            self.assertNotIn('AUTOSCRIPT_INSTALL_FLAVOR', env)
            self.assertNotIn('HTTP_PROXY', env)
            self.assertEqual(Path(env['LOCALAPPDATA']), root / 'profile')
            self.assertEqual(env['BACKEND_URL'], 'http://127.0.0.1:12345')

    def test_port_origin_contract(self):
        self.assertEqual(smoke.PREVIEW_PORTS, {18180, *range(18191, 18200)})
        self.assertFalse(smoke.PREVIEW_PORTS & smoke.FORMAL_PORTS)
        self.assertEqual(smoke.PREVIEW_ORIGIN, 'http://127.0.0.1:18181')
        self.assertEqual(smoke.FORMAL_ORIGIN, 'http://127.0.0.1:18081')

    def test_temporary_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(smoke.temporary_input(Path(directory)), Path(directory).resolve())
        for path in (Path('relative'), Path(tempfile.gettempdir()), Path(__file__).anchor):
            with self.assertRaises(ValueError):
                smoke.temporary_input(Path(path))

    def test_full_hash_manifest_detects_changes_and_additions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = root / 'sentinel'
            item.write_bytes(b'\x00\xff\r\n')
            before = smoke.manifest(root)
            self.assertEqual(len(before['sentinel']), 64)
            item.write_bytes(b'\x00\xff\n')
            self.assertNotEqual(before, smoke.manifest(root))
            item.write_bytes(b'\x00\xff\r\n')
            self.assertEqual(before, smoke.manifest(root))
            (root / 'extra').write_bytes(b'')
            self.assertNotEqual(before, smoke.manifest(root))

    def test_legacy_blob_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy = Path(directory)
            source = legacy / 'client/agent/local_server.py'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'frozen\r\n')
            with patch.object(smoke.subprocess, 'run') as git:
                git.return_value.stdout = b'frozen\n'
                self.assertEqual(smoke.verified_legacy(legacy), b'frozen\n')
                self.assertIn(smoke.FROZEN + ':client/agent/local_server.py', git.call_args.args[0])
                source.write_bytes(b'modified\n')
                with self.assertRaises(ValueError):
                    smoke.verified_legacy(legacy)

    def test_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'real').mkdir()
            try:
                (root / 'link').symlink_to(root / 'real', target_is_directory=True)
            except OSError:
                self.skipTest('symlink privilege unavailable')
            with self.assertRaises(ValueError):
                smoke.temporary_input(root)


if __name__ == '__main__':
    unittest.main()
