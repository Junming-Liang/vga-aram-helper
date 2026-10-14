"""Portable tests of the harness coordinates, environment isolation and gate."""
import copy
import unittest
from windows_dpi_matrix import (EXPECTED_ACCESSIBLE_TIERS, EXPECTED_SOURCE, CASES, SCALES, SCOPE, EXPECTED_CARD_NAMES, EXPECTED_TIERS, case_issues,
    clean_child_environment, contains, expectation_for, rectangle, translation_matches, translation_tolerance_px, validate_matrix)


def good_row(case, scale):
    ident, width, height, offset, _ = case
    expectation=expectation_for(case,scale)
    shown = expectation != 'hidden'
    row = dict(id=ident, expectation=expectation, visible=shown,
        target_fully_onscreen=True, target_native_visible=True, same_process_owned_windows=True,
        target_pmv2=True, overlay_pmv2=True, target_dpi=96,
        qt_window_dpr=float(scale), target_qt_scale_mismatch=float(scale)!=1., target_client_physical=rectangle(10+offset,10+offset,width,height),
        overlay_window_physical=rectangle(20+offset,20+offset, min(width-20, 900), min(height-20, 200)),
        geometry_mapping_matches=True, layout_issues=[], visible_card_count=3 if shown else 0,
        visible_tier_count=3 if shown else 0,
        visible_card_names=list(EXPECTED_CARD_NAMES) if shown else [], visible_tier_text=list(EXPECTED_TIERS) if shown else [],
        visible_source_attribution=EXPECTED_SOURCE if shown else None, tier_accessible_names=list(EXPECTED_ACCESSIBLE_TIERS) if shown else [],
        error=None if shown else 'Layout does not fit', error_type=None if shown else 'CaptureUnavailable')
    return row


def good_matrix():
    return dict(scope=copy.deepcopy(SCOPE), os_name='nt', children=[
        dict(qt_scale_factor=s, status='completed', process_exit_code=0,
            qt_platform='windows', frozen=False, process_pmv2=True,
            owned_windows_destroyed=True, cases=[good_row(c,s) for c in CASES]) for s in SCALES])


class Coordinates(unittest.TestCase):
    def test_fitting_but_obstructive_overlay_is_rejected(self):
        row=good_row(CASES[0],'1')
        row['overlay_window_physical']['height']=302
        self.assertIn('native_overlay_exceeds_half_client_height',case_issues(row))

    def test_negative_monitor_origin_is_legal(self):
        self.assertTrue(contains(rectangle(-1920,0,1920,1080), rectangle(-1910,10,950,230)))
    def test_overflow_is_not_hidden_by_qt_bounds(self):
        self.assertFalse(contains(rectangle(0,0,964,602), rectangle(20,20,1000,230)))
    def test_touching_edges_inside(self):
        self.assertTrue(contains(rectangle(0,0,10,10), rectangle(0,0,10,10)))
    def test_invalid_sizes(self):
        for values in ((0,0,0,10),(0,0,-2,10),(False,0,10,10),(0,0,1.5,10)):
            with self.assertRaises(ValueError): rectangle(*values)


class Gate(unittest.TestCase):
    def test_high_scale_medium_is_optional_fit(self):
        self.assertEqual('fit_or_hide',expectation_for(CASES[3],'2.5'))
        self.assertEqual('visible',expectation_for(CASES[3],'2'))
    def test_case_cannot_weaken_its_own_expectation(self):
        report=good_matrix();report['children'][0]['cases'][0]['expectation']='fit_or_hide'
        self.assertIn('1:wide:case_expectation_changed',validate_matrix(report,'candidate'))
    def test_complete_candidate(self):
        self.assertEqual([], validate_matrix(good_matrix(),'candidate'))
    def test_high_dpi_child_clipping_fails(self):
        report=good_matrix();report['children'][2]['cases'][0]['layout_issues']=['label_height_below_height_for_width']
        self.assertIn('1.5:wide:qt_child_or_text_layout_clipped', validate_matrix(report,'candidate'))
    def test_exception_while_still_visible_fails(self):
        row=good_row(CASES[0], '2');row.update(error='outside', error_type='CaptureUnavailable')
        self.assertIn('error_left_overlay_visible',case_issues(row))
    def test_silent_hiding_cannot_pass(self):
        row=good_row(CASES[4], '2');row.update(visible=False)
        self.assertIn('silent_missing_overlay',case_issues(row))
    def test_explicit_safe_hide_allowed_only_for_optional_fit(self):
        row=good_row(CASES[4], '2');row.update(visible=False,error='small',error_type='CaptureUnavailable')
        self.assertEqual([],case_issues(row))
        row['expectation']='visible'
        self.assertIn('required_visible_layout_missing',case_issues(row))
    def test_unknown_exception_does_not_count_as_safe_hide(self):
        row=good_row(CASES[4],'2');row.update(visible=False,error='missing API',error_type='AttributeError')
        self.assertIn('unexpected_exception_instead_of_safe_rejection',case_issues(row))
    def test_incomplete_scale_matrix_fails(self):
        report=good_matrix();report['children'].pop()
        self.assertIn('scale_matrix_incomplete',validate_matrix(report,'candidate'))
    def test_offscreen_is_never_windows_evidence(self):
        report=good_matrix();report['children'][0]['qt_platform']='offscreen'
        self.assertIn('1:not_real_windows_source_qt',validate_matrix(report,'candidate'))
    def test_frozen_claim_is_rejected(self):
        report=good_matrix();report['children'][0]['frozen']=True
        self.assertIn('1:not_real_windows_source_qt',validate_matrix(report,'candidate'))
    def test_scale_must_actually_apply(self):
        report=good_matrix();report['children'][-1]['cases'][0]['qt_window_dpr']=1.
        self.assertIn('2.5:wide:scale_did_not_take_effect',validate_matrix(report,'candidate'))
    def test_owned_target_must_be_native_visible(self):
        report=good_matrix();report['children'][0]['cases'][0]['target_native_visible']=False
        self.assertIn('1:wide:owned_target_not_native_visible',validate_matrix(report,'candidate'))
    def test_offscreen_target_or_foreign_window_fails(self):
        report=good_matrix();report['children'][0]['cases'][0]['same_process_owned_windows']=False
        self.assertIn('1:wide:ownership_or_visibility_invalid',validate_matrix(report,'candidate'))
    def test_timeout_and_cleanup_failure_fail(self):
        report=good_matrix();report['children'][0]['status']='failed'
        self.assertIn('1:child_incomplete',validate_matrix(report,'candidate'))
        report=good_matrix();report['children'][0]['owned_windows_destroyed']=False
        self.assertIn('1:awareness_or_cleanup_not_verified',validate_matrix(report,'candidate'))
    def test_historical_mode_requires_high_scale_required_fit_regression(self):
        report=good_matrix()
        self.assertIn('historical_high_scale_regression_not_observed',validate_matrix(report,'historical'))
        report['children'][0]['cases'][-2]['visible']=True
        self.assertIn('historical_high_scale_regression_not_observed',validate_matrix(report,'historical'))
        report['children'][3]['cases'][0]['layout_issues']=['label_clipped']
        self.assertEqual([],validate_matrix(report,'historical'))
    def test_historical_unrelated_exception_is_not_dpi_reproduction(self):
        report=good_matrix();report['children'][3]['cases'][0].update(error='unrelated missing attribute',error_type='AttributeError')
        errors=validate_matrix(report,'historical')
        self.assertIn('historical_high_scale_regression_not_observed',errors)
        self.assertIn('2:wide:unexpected_overlay_exception',errors)
    def test_historical_card_loss_is_not_dpi_reproduction(self):
        report=good_matrix();report['children'][3]['cases'][0]['visible_tier_text']=[]
        self.assertIn('historical_high_scale_regression_not_observed',validate_matrix(report,'historical'))
    def test_fixture_cannot_shrink_to_qt_logical_size(self):
        report=good_matrix();report['children'][3]['cases'][0]['target_client_physical']['width']=482
        self.assertIn('2:wide:physical_fixture_size_changed',validate_matrix(report,'candidate'))
    def test_repeat_native_drift_fails(self):
        report=good_matrix();report['children'][0]['cases'][1]['overlay_window_physical']['x']+=1
        self.assertIn('1:repeat_placement_drifted',validate_matrix(report,'candidate'))
    def test_pure_translation_must_preserve_size(self):
        report=good_matrix();report['children'][0]['cases'][2]['overlay_window_physical']['width']-=1
        self.assertIn('1:pure_translation_changed_overlay_size_or_offset',validate_matrix(report,'candidate'))
    def test_card_tier_order_cannot_change(self):
        report=good_matrix();report['children'][0]['cases'][2]['visible_tier_text'].reverse()
        self.assertIn('1:moved:original_card_order_or_tiers_changed',validate_matrix(report,'candidate'))
    def test_shared_source_and_accessible_tiers_fail_closed(self):
        for field,bad in [('visible_source_attribution',None),('visible_source_attribution','虎牙公开源'),('tier_accessible_names',[]),('tier_accessible_names',['T1','T2','T3'])]:
            report=good_matrix();report['children'][0]['cases'][0][field]=bad
            self.assertIn('1:wide:source_attribution_or_accessible_tiers_changed',validate_matrix(report,'candidate'))
    def test_source_scope_cannot_be_overclaimed(self):
        report=good_matrix();report['scope']['real_game_or_vanguard_tested']=True
        self.assertIn('not_actual_windows_source_scope',validate_matrix(report,'candidate'))


class TranslationQuantization(unittest.TestCase):
    def measured_pair(self, dpr, before_rect, after_rect):
        before, after = good_row(CASES[0], str(dpr)), good_row(CASES[2], str(dpr))
        before['overlay_window_physical'] = rectangle(*before_rect)
        after['overlay_window_physical'] = rectangle(*after_rect)
        return before, after

    def test_actual_windows_150_percent_position_rounding(self):
        pair = self.measured_pair(1.5, (29,228,927,366), (33,233,927,366))
        self.assertTrue(translation_matches(*pair))

    def test_actual_windows_200_percent_position_rounding(self):
        pair = self.measured_pair(2, (34,34,916,554), (40,40,916,554))
        self.assertTrue(translation_matches(*pair))

    def test_only_nonintegral_logical_moves_allow_one_physical_pixel(self):
        self.assertEqual([0,0,1,1,0], [translation_tolerance_px(5, float(s)) for s in SCALES])
        self.assertEqual(1, translation_tolerance_px(5, 4))  # Always capped.
        self.assertEqual(0, translation_tolerance_px(0, 2))

    def test_two_physical_pixel_drift_fails_each_axis_and_direction(self):
        for dpr in (1.5, 2):
            for axis in ('x','y'):
                for drift in (-2,2):
                    before, after = self.measured_pair(dpr, (29,100,900,200), (34,105,900,200))
                    after['overlay_window_physical'][axis] += drift
                    self.assertFalse(translation_matches(before, after))

    def test_integral_logical_moves_reject_one_pixel_drift(self):
        for dpr in (1,1.25,2.5):
            before, after = self.measured_pair(dpr, (29,100,900,200), (35,105,900,200))
            self.assertFalse(translation_matches(before, after))

    def test_size_change_gets_no_tolerance(self):
        for dimension in ('width','height'):
            before, after = self.measured_pair(2, (34,34,916,554), (40,40,916,554))
            after['overlay_window_physical'][dimension] += 1
            self.assertFalse(translation_matches(before, after))

    def test_dpr_change_cannot_be_masked_as_translation(self):
        before, after = self.measured_pair(2, (34,34,916,554), (40,40,916,554))
        after['qt_window_dpr'] = 1.5
        self.assertFalse(translation_matches(before, after))

    def test_target_must_actually_move_five_physical_pixels(self):
        before, after = self.measured_pair(2, (34,34,916,554), (40,40,916,554))
        after['target_client_physical']['x'] = before['target_client_physical']['x']
        self.assertFalse(translation_matches(before, after))

    def test_measured_pairs_pass_matrix_gate_without_weakening_repeated_placement(self):
        report = good_matrix()
        for index, dpr, a, b in ((2,1.5,(29,378,927,216),(33,383,927,216)),
                                  (3,2,(34,318,916,270),(40,324,916,270))):
            before, after = self.measured_pair(dpr,a,b)
            rows = report['children'][index]['cases']
            rows[0], rows[2] = before, after
            rows[1]['overlay_window_physical'] = dict(before['overlay_window_physical'])
        self.assertEqual([],validate_matrix(report,'candidate'))
        report['children'][3]['cases'][1]['overlay_window_physical']['x'] += 1
        self.assertIn('2:repeat_placement_drifted',validate_matrix(report,'candidate'))


class Environment(unittest.TestCase):
    def test_only_requested_scale_survives(self):
        before=dict(QT_SCALE_FACTOR='7',Qt_Qpa_Platform='offscreen',QT_SCREEN_SCALE_FACTORS='3;4',
            QT_FONT_DPI='192',QT_ENABLE_HIGHDPI_SCALING='0',Qt_Plugin_Path='unrelated',
            PYTHONPATH='unrelated',PYTHONHOME='unrelated',PATH='python-path',SystemRoot='C:\\Windows')
        after=clean_child_environment(before,'1.5')
        self.assertEqual('1.5',after['QT_SCALE_FACTOR'])
        self.assertEqual('python-path',after['PATH'])
        self.assertEqual('C:\\Windows',after['SYSTEMROOT'])
        for key in ('QT_QPA_PLATFORM','QT_SCREEN_SCALE_FACTORS','QT_FONT_DPI',
                    'QT_ENABLE_HIGHDPI_SCALING','QT_PLUGIN_PATH','PYTHONPATH','PYTHONHOME'):
            self.assertNotIn(key,after)
        self.assertEqual('7',before['QT_SCALE_FACTOR'])
        self.assertEqual('1',after['PYTHONDONTWRITEBYTECODE'])


if __name__=='__main__': unittest.main()
