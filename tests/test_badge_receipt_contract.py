"""Static producer/consumer schema check, not a substitute for native evidence."""
import ast
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
FIELDS={'source_hint_renderer_passed','source_hint_render_scope','source_hint_visible_text','card_names_accessible','badge_source_markers','source_tier_rendered',
        'source_tier_accessible','three_badge_regions_verified','source_details_reachable','badge_gap_hit_test_passed','badge_above_cards_verified','badge_revocation_hidden_verified'}


def literals(path):
    return {n.value for n in ast.walk(ast.parse(path.read_text(encoding='utf8')))
            if isinstance(n,ast.Constant) and isinstance(n.value,str)}


class BadgeReceiptContract(unittest.TestCase):
    def test_native_producer_and_both_strict_consumers_agree(self):
        tree=ast.parse((ROOT/'native_smoke.py').read_text(encoding='utf8'))
        produced=literals(ROOT/'native_smoke.py')|{n.arg for n in ast.walk(tree) if isinstance(n,ast.keyword)}
        self.assertLessEqual(FIELDS,produced)
        for file in ('tests/windows_native_smoke.py','scripts/verify_release.py'):
            self.assertLessEqual(FIELDS,literals(ROOT/file),file)
        for file in ('native_smoke.py','tests/windows_native_smoke.py','scripts/verify_release.py'):
            self.assertFalse({'card_names_rendered','source_attribution_rendered'} & literals(ROOT/file),file)

    def test_exact_region_receipt_rejects_strip_overlap_size_and_card_drift(self):
        import copy
        from overlay_duty_contract import validate_badge_regions
        from test_native_packaging import NativePackagingTests
        good=NativePackagingTests.badge_receipt_fixture(NativePackagingTests.geometry_fixture())
        validate_badge_regions(good)
        mutations=[lambda v:v['badge_regions_physical'].pop(),
            lambda v:v['badge_regions_physical'][0].__setitem__(2,920),
            lambda v:v['badge_regions_physical'][1].__setitem__(0,0),
            lambda v:v['badge_card_bounds_physical'][0].__setitem__(1,0),
            lambda v:v['overlay_window_physical'].__setitem__('height',240)]
        for mutate in mutations:
            value=copy.deepcopy(good);mutate(value)
            with self.assertRaises(RuntimeError):validate_badge_regions(value)

    def test_matrix_requires_native_shape_anchor_gap_and_lifecycle_proof(self):
        from windows_dpi_matrix import validate_matrix
        from test_windows_dpi_matrix import good_matrix
        for field in ('native_badge_regions_verified','badge_above_cards_verified','gap_hit_test_passed'):
            report=good_matrix();report['children'][0]['cases'][0][field]=False
            self.assertTrue(validate_matrix(report,'candidate'),field)
        report=good_matrix();report['children'][0]['badge_lifecycle_verified']=False
        self.assertIn('1:badge_lifecycle_not_verified',validate_matrix(report,'candidate'))

if __name__=='__main__':unittest.main()
