"""Model preparation concurrency with owned mocks; no OCR speed/accuracy claim."""
import io
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from local_ocr import LocalOCR

try:
    import numpy
    from PIL import Image
except ImportError:
    Image = None


class LocalOCRPrepareTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.engine = Mock(return_value=SimpleNamespace(
            txts=['alpha'], scores=[.99], boxes=None, elapse_list=[.01]))
        self.constructor = Mock(side_effect=lambda **kwargs:
            self.events.append('constructor') or self.engine)
        self.module = SimpleNamespace(__file__='/tmp/owned-rapidocr/__init__.py',
                                      RapidOCR=self.constructor)
        for manager in (
            patch.dict('sys.modules', {'rapidocr': self.module}),
            patch('local_ocr.load_private_onnxruntime',
                  side_effect=lambda: self.events.append('telemetry')),
            patch('model_inventory.verify_models',
                  side_effect=lambda path: self.events.append('verify')),
        ):
            manager.start()
            self.addCleanup(manager.stop)
        self.ocr = LocalOCR()
        self.errors = []
        self.threads = []

    def launch(self, function):
        def run():
            try:
                function()
            except BaseException as exc:
                self.errors.append(exc)
        thread = threading.Thread(target=run, daemon=True)
        self.threads.append(thread)
        thread.start()
        return thread

    def join(self):
        for thread in self.threads:
            thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(self.errors, [])

    @staticmethod
    def image():
        output = io.BytesIO()
        Image.new('RGB', (32, 32), (11, 22, 33)).save(output, format='PNG')
        return output.getvalue()

    def test_prepare_is_idempotent_verifies_models_and_never_infers(self):
        with patch('local_ocr.candidate_matches') as matches:
            self.assertIsNone(self.ocr.prepare())
            self.assertIsNone(self.ocr.prepare())
            matches.assert_not_called()
        self.assertEqual(self.events, ['telemetry', 'verify', 'constructor'])
        self.engine.assert_not_called()
        self.assertIs(self.ocr._engine, self.engine)
        params = self.constructor.call_args.kwargs['params']
        root = Path(self.module.__file__).resolve().parent / 'models'
        self.assertEqual(params, {
            'Det.model_path': str(root / 'PP-OCRv6_det_small.onnx'),
            'Rec.model_path': str(root / 'PP-OCRv6_rec_small.onnx'),
            'Cls.model_path': str(root / 'ch_ppocr_mobile_v2.0_cls_mobile.onnx'),
            'Global.use_cls': False, 'Det.limit_type': 'max',
            'Det.limit_side_len': 960,
            'EngineConfig.onnxruntime.intra_op_num_threads': 2,
            'EngineConfig.onnxruntime.inter_op_num_threads': 1,
        })

    def test_concurrent_prepare_creates_only_one_engine(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def construct(**kwargs):
            entered.set()
            self.assertTrue(release.wait(2))
            return self.engine
        self.constructor.side_effect = construct
        self.launch(self.ocr.prepare)
        self.assertTrue(entered.wait(2))
        for _ in range(7):
            self.launch(self.ocr.prepare)
        release.set()
        self.join()
        self.constructor.assert_called_once()
        self.assertEqual(self.events, ['telemetry', 'verify'])
        self.engine.assert_not_called()

    @unittest.skipIf(Image is None, 'Optional image dependencies are not installed')
    def test_recognition_waits_for_preparation_then_uses_same_engine(self):
        entered, release, finished = (threading.Event() for _ in range(3))
        self.addCleanup(release.set)
        def construct(**kwargs):
            entered.set()
            self.assertTrue(release.wait(2))
            return self.engine
        self.constructor.side_effect = construct
        self.launch(self.ocr.prepare)
        self.assertTrue(entered.wait(2))
        image = self.image()
        values = []
        def recognize():
            values.append(self.ocr.recognize(image, ('alpha',)))
            finished.set()
        self.launch(recognize)
        self.assertFalse(finished.wait(.05))
        self.engine.assert_not_called()
        release.set()
        self.join()
        self.constructor.assert_called_once()
        self.engine.assert_called_once()
        self.assertEqual(values[0]['candidates'][0]['name'], 'alpha')

    @unittest.skipIf(Image is None, 'Optional image dependencies are not installed')
    def test_prepare_does_not_overlap_active_inference(self):
        self.ocr.prepare()
        entered, release, prepared = (threading.Event() for _ in range(3))
        self.addCleanup(release.set)
        output = self.engine.return_value
        def infer(image):
            entered.set()
            self.assertTrue(release.wait(2))
            return output
        self.engine.side_effect = infer
        image = self.image()
        self.launch(lambda: self.ocr.recognize(image, ('alpha',)))
        self.assertTrue(entered.wait(2))
        self.launch(lambda: (self.ocr.prepare(), prepared.set()))
        self.assertFalse(prepared.wait(.05))
        release.set()
        self.join()
        self.constructor.assert_called_once()

    def test_failed_verification_or_construction_can_retry(self):
        for stage in ('verify', 'constructor'):
            with self.subTest(stage=stage):
                ocr = LocalOCR()
                if stage == 'verify':
                    manager = patch('model_inventory.verify_models',
                                    side_effect=[RuntimeError('owned failure'), None])
                else:
                    manager = patch.object(self.module, 'RapidOCR',
                                           side_effect=[RuntimeError('owned failure'), self.engine])
                with manager:
                    with self.assertRaisesRegex(RuntimeError, 'owned failure'):
                        ocr.prepare()
                    self.assertIsNone(ocr._engine)
                    self.assertIsNone(ocr.prepare())
                    self.assertIs(ocr._engine, self.engine)
        self.engine.assert_not_called()

    def test_missing_optional_runtime_has_existing_actionable_error(self):
        with patch('local_ocr.load_private_onnxruntime', side_effect=ImportError('owned')):
            with self.assertRaisesRegex(RuntimeError, 'requirements-ocr.txt'):
                self.ocr.prepare()
        self.assertIsNone(self.ocr._engine)
        self.constructor.assert_not_called()

    @unittest.skipIf(Image is None, 'Optional image dependencies are not installed')
    def test_invalid_image_does_not_initialize_models(self):
        for image in (b'', b'not an image', None):
            with self.subTest(image=image), self.assertRaises(ValueError):
                self.ocr.recognize(image, ('alpha',))
        self.constructor.assert_not_called()
        self.assertEqual(self.events, [])

    @unittest.skipIf(Image is None, 'Optional image dependencies are not installed')
    def test_prepared_and_lazy_recognition_match_without_fake_observation(self):
        self.ocr.prepare()
        self.engine.assert_not_called()
        prepared = self.ocr.recognize(self.image(), ('alpha',))
        lazy = LocalOCR().recognize(self.image(), ('alpha',))
        self.assertEqual(prepared, lazy)
        self.assertEqual(self.engine.call_count, 2)
        self.assertNotIn('_capturedAt', prepared)
        self.assertNotIn('ocr_reused', prepared)
        self.assertEqual(self.engine.call_args.args[0][0, 0].tolist(), [33, 22, 11])


if __name__ == '__main__':
    unittest.main()
