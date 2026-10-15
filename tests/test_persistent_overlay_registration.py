"""Exact owned opaque overlay enrollment; portable Win32 fakes only."""
import ctypes
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from screen_capture import Win32Capture, CaptureUnavailable
from persistent_capture_adapter import PersistentCaptureAdapter
from wgc_capture import WgcError
from test_overlay_style_refresh import FakeWin32, REQUIRED, TRANSPARENT, TOPMOST

STYLE = REQUIRED | TRANSPARENT


class OpaqueWin32(FakeWin32):
    def __init__(self):
        super().__init__({101: STYLE, 102: STYLE})
        self.owner = os.getpid()
        self.owner_query = True
        self.root = 101
        self.exists = True
        self.visible = False
        self.affinity = 0x11
        self.affinity_query = True
        self.affinity_effective = 0x11
        self.layered = (0, 255, 2)
        self.layered_query = True
        self.layered_result = True
        self.before_write = self.before_affinity = self.before_layered = None
        self.final_style_drift = False

    def IsWindow(self, hwnd): return self.exists
    def GetAncestor(self, hwnd, mode): return self.root
    def IsWindowVisible(self, hwnd): return self.visible

    def GetWindowThreadProcessId(self, hwnd, pointer):
        pointer._obj.value = self.owner
        return int(self.owner_query)

    def GetWindowDisplayAffinity(self, hwnd, pointer):
        pointer._obj.value = self.affinity
        self.calls.append(('affinity-read', hwnd, self.affinity))
        return self.affinity_query

    def SetWindowDisplayAffinity(self, hwnd, affinity):
        if self.before_affinity: self.before_affinity()
        result = super().SetWindowDisplayAffinity(hwnd, affinity)
        if result: self.affinity = self.affinity_effective
        if self.final_style_drift: self.styles[hwnd] |= 0x100
        return result

    def GetLayeredWindowAttributes(self, hwnd, color, alpha, flags):
        color._obj.value, alpha._obj.value, flags._obj.value = self.layered
        self.calls.append(('opaque-read', hwnd, self.layered))
        return self.layered_query

    def SetLayeredWindowAttributes(self, hwnd, color, alpha, flags):
        if self.before_layered: self.before_layered()
        self.calls.append(('opaque-write', hwnd, color, alpha, flags))
        if self.layered_result: self.layered = (color, alpha, flags)
        return self.layered_result

    def set_long(self, *args):
        if self.before_write: self.before_write()
        return super().set_long(*args)


class OverlayRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.api = OpaqueWin32()
        self.capture = object.__new__(Win32Capture)
        self.capture.u = self.api
        self.capture.get_long = self.api.get_long
        self.capture.set_long = self.api.set_long
        self.capture._overlay_hwnd = None
        self.capture._persistent = PersistentCaptureAdapter(self.capture._check_session_overlay)
        self.addCleanup(self.capture.close)
        for name in ('set_last_error', 'get_last_error'):
            patcher = patch.object(ctypes, name, getattr(self.api, name), create=True)
            patcher.start(); self.addCleanup(patcher.stop)

    def configure(self):
        return self.capture.configure_overlay(101, opaque=True)

    def test_exact_self_owned_full_style_opaque_and_affinity_registers(self):
        self.assertTrue(self.configure())
        overlay = self.capture._persistent.overlay
        self.assertEqual((overlay.hwnd, overlay.extended_style), (101, STYLE))
        self.capture._check_session_overlay(overlay)

    def test_unchanged_refresh_rechecks_without_layered_or_affinity_mutation(self):
        for _ in range(3): self.assertTrue(self.configure())
        self.assertEqual(self.api.of_kind('opaque-write'), [])
        self.assertEqual(self.api.of_kind('affinity'), [])
        self.assertEqual(self.api.of_kind('write'), [])
        self.assertEqual(self.capture._persistent.overlay.generation, 1)
        self.assertGreaterEqual(len(self.api.of_kind('opaque-read')), 6)
        self.assertGreaterEqual(len(self.api.of_kind('affinity-read')), 6)

    def test_missing_foreign_or_child_window_fails_before_mutation(self):
        for field, value in (('exists', False), ('owner', os.getpid() + 1),
                             ('owner_query', False), ('root', 999)):
            with self.subTest(field=field):
                old = getattr(self.api, field); setattr(self.api, field, value)
                with self.assertRaises(CaptureUnavailable): self.configure()
                for kind in ('write', 'position', 'affinity', 'opaque-write'):
                    self.assertEqual(self.api.of_kind(kind), [])
                self.assertIsNone(self.capture._persistent.overlay)
                setattr(self.api, field, old)

    def test_unexpected_full_style_change_is_rejected_not_just_required_bits(self):
        self.api.after_position = STYLE | 0x100
        with self.assertRaises(CaptureUnavailable): self.configure()
        self.assertEqual(self.api.of_kind('affinity'), [])
        self.assertIsNone(self.capture._persistent.overlay)

    def test_mutated_style_is_revoked_before_repair(self):
        self.configure()
        self.api.styles[101] &= ~TRANSPARENT
        self.api.before_write = lambda: self.assertIsNone(self.capture._persistent.overlay)
        self.configure()
        self.assertEqual(self.capture._persistent.overlay.generation, 3)

    def test_affinity_drift_revokes_before_repair(self):
        self.configure(); self.api.affinity = 1
        self.api.before_affinity = lambda: self.assertIsNone(self.capture._persistent.overlay)
        self.configure()
        self.assertEqual(self.api.affinity, 0x11)
        self.assertEqual(self.capture._persistent.overlay.generation, 3)

    def test_opaque_drift_revokes_before_repair(self):
        self.configure(); self.api.layered = (0, 128, 2)
        self.api.before_layered = lambda: self.assertIsNone(self.capture._persistent.overlay)
        self.configure()
        self.assertEqual(self.api.layered, (0, 255, 2))
        self.assertEqual(len(self.api.of_kind('opaque-write')), 1)

    def test_affinity_success_without_exact_readback_never_registers(self):
        for effective, query in ((0, True), (1, True), (0x11, False)):
            with self.subTest(effective=effective, query=query):
                self.api.affinity = 0; self.api.affinity_effective = effective; self.api.affinity_query = query
                self.assertFalse(self.configure())
                self.assertIsNone(self.capture._persistent.overlay)

    def test_failed_opaque_profile_never_registers(self):
        for value in ((0, 128, 2), (0, 255, 1), (1, 255, 2)):
            with self.subTest(value=value):
                self.api.layered = value; self.api.layered_result = False
                with self.assertRaises(CaptureUnavailable): self.configure()
                self.assertIsNone(self.capture._persistent.overlay)

    def test_post_affinity_full_style_drift_denied(self):
        self.api.affinity = 0; self.api.final_style_drift = True
        with self.assertRaises(CaptureUnavailable): self.configure()
        self.assertIsNone(self.capture._persistent.overlay)

    def test_clickable_or_legacy_translucent_overlay_never_registers(self):
        self.assertTrue(self.capture.configure_overlay(101, False, opaque=True))
        self.assertIsNone(self.capture._persistent.overlay)
        self.assertTrue(self.capture.configure_overlay(101, True, opaque=False))
        self.assertIsNone(self.capture._persistent.overlay)

    def test_live_worker_proof_rejects_each_owner_style_affinity_opacity_or_visibility_change(self):
        self.configure(); overlay = self.capture._persistent.overlay
        for field, value in (('owner', os.getpid() + 1), ('root', 102), ('exists', False),
                             ('affinity', 1), ('affinity_query', False), ('visible', True),
                             ('layered', (1, 255, 2)), ('layered_query', False)):
            with self.subTest(field=field):
                old = getattr(self.api, field); setattr(self.api, field, value)
                with self.assertRaises(WgcError): self.capture._check_session_overlay(overlay)
                setattr(self.api, field, old)
        self.api.styles[101] |= 0x100
        with self.assertRaises(WgcError): self.capture._check_session_overlay(overlay)

    def test_registration_of_a_different_hwnd_uses_new_generation(self):
        self.configure(); self.api.root = 102
        self.capture.configure_overlay(102, opaque=True)
        overlay = self.capture._persistent.overlay
        self.assertEqual((overlay.hwnd, overlay.generation), (102, 3))


if __name__ == '__main__': unittest.main()
