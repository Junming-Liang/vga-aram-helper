"""Portable evidence forwarding only; no native Windows capture claim."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import wgc_smoke
from wgc_capture import WgcError


def diagnostic():
    return {'schema_version': 1, 'code': 12, 'phase': 'validate-initial',
            'check': 'window-visible', 'hresult': 0, 'style': 0, 'extended_style': 0,
            'observed': [0, 0, 320, 240], 'expected': [0, 0, 320, 240],
            'window_rect': [30, 30, 336, 278], 'frame_rect': [38, 30, 320, 270]}


class WgcSmokeDiagnosticTests(unittest.TestCase):
    def test_direct_and_explicit_routed_cause_preserve_validated_evidence(self):
        error = WgcError('stale', 'owned rejection', diagnostic())
        for exception in (error, RuntimeError('routed rejection')):
            if exception is not error:
                exception.__cause__ = error
            result = wgc_smoke.failure_evidence(exception)
            self.assertEqual(result, {'native_diagnostic': diagnostic()})
            result['native_diagnostic']['observed'][0] = 99
            self.assertEqual(error.diagnostic['observed'][0], 0)

    def test_unrelated_exception_attributes_and_implicit_context_are_not_evidence(self):
        error = RuntimeError('ordinary failure')
        error.diagnostic = diagnostic()
        error.__context__ = WgcError('stale', 'unrelated context', diagnostic())
        self.assertEqual(wgc_smoke.failure_evidence(error), {})

    def test_mutated_private_extra_field_is_rejected_again_before_reporting(self):
        error = WgcError('stale', 'owned rejection', diagnostic())
        error.diagnostic['window_title'] = 'never publish arbitrary attributes'
        self.assertEqual(wgc_smoke.failure_evidence(error), {})

    def test_cyclic_and_excessively_long_causes_are_bounded(self):
        error = RuntimeError('cycle')
        error.__cause__ = error
        self.assertEqual(wgc_smoke.failure_evidence(error), {})
        error = WgcError('stale', 'outside allowed depth', diagnostic())
        for _ in range(8):
            outer = RuntimeError('wrapper')
            outer.__cause__ = error
            error = outer
        self.assertEqual(wgc_smoke.failure_evidence(error), {})

    def test_failed_report_contains_diagnostic_without_becoming_a_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'report.json'
            error = WgcError('stale', 'owned rejection', diagnostic())
            with patch.object(wgc_smoke, 'execute', side_effect=error):
                self.assertEqual(wgc_smoke.run(path), 1)
            result = json.loads(path.read_text())
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['error_type'], 'WgcError')
            self.assertEqual(result['native_diagnostic'], diagnostic())
            self.assertFalse(result.get('owned_hwnd_pixels_passed', False))

    def test_ordinary_failure_report_does_not_require_native_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'report.json'
            with patch.object(wgc_smoke, 'execute', side_effect=RuntimeError('owned failure')):
                self.assertEqual(wgc_smoke.run(path), 1)
            result = json.loads(path.read_text())
            self.assertEqual(result['status'], 'failed')
            self.assertNotIn('native_diagnostic', result)


if __name__ == '__main__':
    unittest.main()
