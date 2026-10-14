"""License/source distribution gates are offline and fail closed."""
import hashlib
import io
from pathlib import Path
import shutil
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qt_licenses
from scripts.build_windows import assert_archive_inventory, verify_source_checkout


class QtLicensesTests(unittest.TestCase):
    def test_windows_git_checkout_preserves_verbatim_notice_bytes(self):
        relative = Path('packaging/qt-licenses/pyside-setup/LICENSES/Apache-2.0.txt')
        original = (ROOT / relative).read_bytes()
        self.assertIn(b'\n', original)
        self.assertNotIn(b'\r\n', original)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def git(*args):
                return subprocess.run(['git', '-c', 'core.autocrlf=true', *args], cwd=root,
                                      check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            git('init')
            shutil.copyfile(ROOT / '.gitattributes', root / '.gitattributes')
            (root / relative).parent.mkdir(parents=True)
            (root / relative).write_bytes(original)
            git('add', '.gitattributes', relative.as_posix())
            (root / relative).unlink()
            git('checkout-index', '--force', '--all')
            self.assertEqual((root / relative).read_bytes(), original)
            self.assertEqual(git('show', ':' + relative.as_posix()).stdout, original)

    def test_source_archive_requires_clean_tracked_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def git(*args):
                return subprocess.run(['git', *args], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            git('init')
            (root/'app.py').write_text('print("original")\n')
            (root/'.gitignore').write_text('__pycache__/\n*.py\n')
            git('add','-f','app.py','.gitignore')
            git('-c','user.name=Packaging test','-c','user.email=packaging-test@example.invalid','commit','--no-gpg-sign','-m','Original fixture')
            commit = verify_source_checkout(root)
            (root/'reports').mkdir();(root/'reports/windows-build-environment.txt').write_text('generated log')
            self.assertEqual(verify_source_checkout(root,commit),commit)
            with self.assertRaisesRegex(RuntimeError,'differs'):
                verify_source_checkout(root,'0'*40)
            (root/'app.py').write_text('print("changed")\n')
            with self.assertRaisesRegex(RuntimeError,'clean Git checkout'):
                verify_source_checkout(root)
            (root/'app.py').write_text('print("original")\n')
            (root/'ignored_runtime.py').write_text('untracked = True\n')
            with self.assertRaisesRegex(RuntimeError,'Untracked or symbolic'):
                verify_source_checkout(root)

    def test_checked_in_verbatim_notices_are_complete(self):
        data = qt_licenses.verify_bundle(ROOT / 'packaging/qt-licenses')
        self.assertEqual(len(data['files']), 149)
        self.assertEqual(sum(entry['size'] for entry in data['archives']), 73_028_200)

    def test_license_copy_preserves_paths_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            shutil.copytree(ROOT / 'packaging/qt-licenses', source)
            data, files = qt_licenses.copy_bundle(source, root / 'licenses')
            self.assertIn('qt-licenses/pyside-setup/LICENSES/LGPL-3.0-only.txt', files)
            (source / data['files'][0]['path']).write_text('changed')
            with self.assertRaisesRegex(RuntimeError, 'missing or changed'):
                qt_licenses.copy_bundle(source, root / 'bad')

    def test_source_download_checks_exact_size_hash_and_removes_partial(self):
        content = b'original source archive fixture'
        entry = {'url':'https://download.qt.io/official_releases/source.tar.xz',
                 'upstream_filename':'source.tar.xz', 'size':len(content),
                 'sha256':hashlib.sha256(content).hexdigest()}
        with tempfile.TemporaryDirectory() as temporary, patch.object(qt_licenses, 'verify_bundle', return_value={'archives':[entry]}):
            root = Path(temporary)
            result = qt_licenses.supply_sources(root, root, opener=lambda *a, **k:io.BytesIO(content))
            self.assertEqual((root/'source.tar.xz').read_bytes(), content)
            self.assertEqual(result[0]['sha256'], entry['sha256'])
            for bad in (content[:-1], content+b'extra', b'x'*len(content)):
                with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                    qt_licenses.supply_sources(root, root, opener=lambda *a, **k:io.BytesIO(bad))
                self.assertFalse(list(root.glob('*.partial')))
                self.assertEqual((root/'source.tar.xz').read_bytes(), content)

    def test_archive_inventory_lists_qt_and_rejects_unlicensed_optional_runtimes(self):
        names = ['python312.dll','vcruntime140.dll','vcruntime140_1.dll','msvcp140.dll',
                 'PySide6/Qt6Core.dll','PySide6/Qt6Gui.dll','PySide6/Qt6Widgets.dll',
                 'PySide6/plugins/platforms/qwindows.dll','static/index.html',
                 'fixtures/ocr-synthetic.png','fixtures/ocr-blank.png','assets/branding/vga.ico', 'native/vga-wgc-capture.exe', 'native/wgc-capture-build.json']
        names += ['rapidocr/models/'+name for name in ('PP-OCRv6_det_small.onnx','PP-OCRv6_rec_small.onnx','ch_ppocr_mobile_v2.0_cls_mobile.onnx')]
        result = assert_archive_inventory(names)
        self.assertIn('pyside6/qt6widgets.dll',result['qt_binaries'])
        for forbidden in ('PySide6/Qt6WebEngineCore.dll','PySide6/opengl32sw.dll','PySide6/d3dcompiler_47.dll',
                          'PySide6/plugins/tls/qopensslbackend.dll','PySide6/plugins/imageformats/qpdf.dll','PySide6/Qt6Pdf.dll'):
            with self.subTest(forbidden=forbidden), self.assertRaises(RuntimeError):
                assert_archive_inventory(names+[forbidden])


if __name__ == '__main__':
    unittest.main()
