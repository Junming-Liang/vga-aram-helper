"""Fresh interpreters and fake imports prove ordering without initializing ORT."""
import ast
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class OCRPrivacyTests(unittest.TestCase):
    def test_every_source_entry_sets_full_opt_out_without_loading_runtime(self):
        for module in ('ocr_privacy', 'local_ocr', 'model_inventory', 'launcher'):
            code = ("import os,sys;os.environ['ORT_DISABLE_TELEMETRY']='0';"
                    f"__import__({module!r});"
                    "assert os.environ['ORT_DISABLE_TELEMETRY']=='1';"
                    "assert 'onnxruntime' not in sys.modules")
            subprocess.run([sys.executable, '-c', code], cwd=ROOT, check=True,
                           capture_output=True, timeout=10)

    def test_environment_precedes_native_import_and_api_precedes_return(self):
        code = '''
import builtins, os, types
import ocr_privacy
os.environ['ORT_DISABLE_TELEMETRY'] = '0'
events = []
original = builtins.__import__
def fake_import(name, *args, **kwargs):
    if name == 'onnxruntime':
        if os.environ.get('ORT_DISABLE_TELEMETRY') != '1':
            raise RuntimeError('ORT native import preceded process opt-out')
        events.append('import-disabled')
        return types.SimpleNamespace(disable_telemetry_events=lambda: events.append('api-disabled'))
    return original(name, *args, **kwargs)
builtins.__import__ = fake_import
ocr_privacy.load_private_onnxruntime()
if events != ['import-disabled', 'api-disabled']:
    raise RuntimeError(events)
'''
        subprocess.run([sys.executable, '-c', code], cwd=ROOT, check=True,
                       capture_output=True, timeout=10)

    def test_api_disable_is_not_silently_swallowed(self):
        import ocr_privacy
        with patch.dict(sys.modules, {'onnxruntime': type('BrokenORT', (), {
                'disable_telemetry_events': staticmethod(lambda: (_ for _ in ()).throw(RuntimeError('blocked')))
            })()}):
            with self.assertRaisesRegex(RuntimeError, 'blocked'):
                ocr_privacy.load_private_onnxruntime()

    def test_api_disable_precedes_rapidocr_loading_in_recognize(self):
        tree = ast.parse((ROOT/'local_ocr.py').read_text())
        recognize = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'recognize')
        disabled = [node.lineno for node in ast.walk(recognize) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == 'load_private_onnxruntime']
        imports = [node.lineno for node in ast.walk(recognize) if isinstance(node, ast.ImportFrom) and node.module == 'rapidocr']
        self.assertEqual(len(disabled), 1); self.assertEqual(len(imports), 1)
        self.assertLess(disabled[0], imports[0])

    def test_candidate_workflow_sets_opt_out_before_any_python_process(self):
        workflow = (ROOT/'.github/workflows/test-windows-minimal-opencv.yml').read_text()
        self.assertIn("      ORT_DISABLE_TELEMETRY: '1'", workflow)


if __name__ == '__main__':
    unittest.main()
