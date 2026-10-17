"""Partial titles need real three-column evidence; no pixels/network needed."""
from copy import deepcopy
import unittest

from partial_candidates import EMPTY_SLOTS, PartialCandidateState, title_evidence


NAMES = ('星火共鸣', '晶盾回路', '风步微光', '旧日回声')
SIZE = {'width': 900, 'height': 300}
CONTEXT = ('window-1', 'roi-1', 'source-1', 'hero-1', 'scene-1')


def rows(names=NAMES[:3], scores=(.99, .99, .99)):
    return [{'text': name, 'confidence': score,
             'box': [[x - 45, 105], [x + 45, 105], [x + 45, 135], [x - 45, 135]]}
            for name, score, x in zip(names, scores, (150, 450, 750))]


def evidence(lines=None, **kwargs):
    return title_evidence(rows() if lines is None else lines, kwargs.pop('size', SIZE),
                          kwargs.pop('vocabulary', NAMES),
                          crop_top=kwargs.pop('crop_top', 180),
                          frame_height=kwargs.pop('frame_height', 720), **kwargs)


class TitleEvidenceTests(unittest.TestCase):
    def test_three_aligned_exact_titles_have_fixed_slots(self):
        value = evidence(list(reversed(rows())))
        self.assertTrue(value.valid)
        self.assertEqual(tuple(slot.slot for slot in value.slots), (1, 2, 3))
        self.assertEqual(tuple(slot.name for slot in value.slots), NAMES[:3])

    def test_unknown_third_title_is_geometry_not_guessed_name(self):
        value = evidence(rows((NAMES[0], '尚未收录的名称', NAMES[2])))
        self.assertTrue(value.valid)
        self.assertEqual(tuple(slot.name for slot in value.slots), (NAMES[0], '', NAMES[2]))

    def test_low_confidence_title_is_blank_but_has_box(self):
        for score in (0, .54, .85, .929999):
            with self.subTest(score=score):
                value = evidence(rows(scores=(.99, score, .99)))
                self.assertTrue(value.valid)
                self.assertEqual(value.slots[1].name, '')
        self.assertEqual(evidence(rows(scores=(.93, .93, .93))).slots[1].name, NAMES[1])

    def test_two_titles_cannot_invent_third_geometry(self):
        self.assertFalse(evidence(rows()[:2]).valid)

    def test_extra_title_row_or_duplicate_column_rejects(self):
        self.assertFalse(evidence(rows() + rows()[:1]).valid)
        value = rows()
        value[2]['box'] = deepcopy(value[1]['box'])
        self.assertFalse(evidence(value).valid)

    def test_repeated_title_rejects_even_if_layout_aligned(self):
        self.assertFalse(evidence(rows((NAMES[0], NAMES[0], NAMES[2]))).valid)

    def test_symbol_only_decoration_cannot_supply_title_geometry(self):
        decoration = {'text': '●', 'confidence': .85,
                      'box': [[20, 165], [38, 165], [38, 182], [20, 182]]}
        self.assertTrue(evidence(rows() + [decoration]).valid)
        self.assertFalse(evidence(rows()[:2] + [decoration]).valid)

    def test_unicode_and_digit_titles_remain_textual_rows(self):
        value = evidence(rows(('ＡＢＣ', '123', NAMES[2])), vocabulary=('ABC', '123', NAMES[2]))
        self.assertTrue(value.valid)
        self.assertEqual(tuple(slot.name for slot in value.slots), ('ABC', '123', NAMES[2]))

    def test_title_band_uses_full_frame_not_crop_coordinates(self):
        self.assertTrue(evidence().valid)
        self.assertFalse(evidence(crop_top=0).valid)
        self.assertFalse(evidence(crop_top=420).valid)

    def test_out_of_band_rows_do_not_supply_missing_title(self):
        value = rows()
        value[2]['box'] = [[705, 230], [795, 230], [795, 260], [705, 260]]
        self.assertFalse(evidence(value).valid)
        self.assertTrue(evidence(rows() + [value[2]]).valid)

    def test_misalignment_and_implausible_size_reject(self):
        for box in ([[405, 130], [495, 130], [495, 160], [405, 160]],
                    [[405, 105], [800, 105], [800, 135], [405, 135]],
                    [[405, 105], [495, 105], [495, 106], [405, 106]]):
            value = rows()
            value[1]['box'] = box
            self.assertFalse(evidence(value).valid)

    def test_malformed_boxes_and_nonfinite_inputs_reject(self):
        for box in (None, [], [[1, 2]], [[float('nan'), 105]] * 4,
                    [[105, 105], [195, 135], [105, 105], [195, 135]],
                    [[True, 105], [195, 105], [195, 135], [105, 135]],
                    [[-1, 105], [195, 105], [195, 135], [-1, 135]]):
            value = rows()
            value[0]['box'] = box
            self.assertFalse(evidence(value).valid)
        for score in (float('nan'), float('inf'), True, '0.99', -.1, 1.1, None):
            self.assertFalse(evidence(rows(scores=(score, .99, .99))).valid)
        for size in (None, {}, {'width': True, 'height': 300},
                     {'width': float('inf'), 'height': 300}):
            self.assertFalse(evidence(size=size).valid)
        for top in (-1, True, float('nan'), 500):
            self.assertFalse(evidence(crop_top=top).valid)

    def test_malformed_extra_row_cannot_be_silently_dropped(self):
        for row in (None, {}, {'text': 'extra', 'confidence': .99, 'box': None}):
            self.assertFalse(evidence(rows() + [row]).valid)

    def test_literal_exact_only_preserves_punctuation_and_ambiguity(self):
        for text in ('选择星火共鸣', '星火共呜', '【星火共鸣】'):
            value = evidence(rows((text, NAMES[1], NAMES[2])))
            self.assertTrue(value.valid)
            self.assertEqual(value.slots[0].name, '')
        self.assertEqual(evidence(rows(('星 火共鸣', NAMES[1], NAMES[2]))).slots[0].name, NAMES[0])
        self.assertEqual(evidence(vocabulary=(*NAMES, '星 火共鸣')).slots[0].name, '')

    def test_no_dictionary_candidates_can_replace_raw_rows(self):
        candidates = [{'name': item['text'], 'recognized_text': item['text'],
                       'ocr_confidence': item['confidence'], 'match_method': 'exact',
                       'box': item['box']} for item in rows()]
        self.assertFalse(evidence(candidates).valid)

    def test_does_not_mutate_inputs_or_keep_mutable_boxes(self):
        value = rows()
        original = deepcopy(value)
        result = evidence(value)
        self.assertEqual(value, original)
        value[0]['box'][0][0] = 999
        self.assertEqual(result.slots[0].box[0][0], 105)


class PartialCandidateStateTests(unittest.TestCase):
    def setUp(self):
        self.state = PartialCandidateState()

    def observe(self, serial, lines=None, **kwargs):
        return self.state.observe(evidence(lines), frame_serial=serial,
                                  captured_at=kwargs.pop('captured_at', serial),
                                  now=kwargs.pop('now', serial),
                                  context=kwargs.pop('context', CONTEXT),
                                  guards_passed=kwargs.pop('guards_passed', True),
                                  ocr_reused=kwargs.pop('ocr_reused', False), **kwargs)

    def stable(self):
        self.assertEqual(self.observe(1), EMPTY_SLOTS)
        self.assertEqual(self.observe(2), NAMES[:3])

    def test_early_recheck_is_revocation_only_and_final_counts_once(self):
        self.stable()
        stamps=(self.state._last_serial,self.state._last_capture,self.state._last_ocr)
        changed=evidence(rows((NAMES[0],NAMES[3],NAMES[2])))
        self.assertEqual(self.state.recheck(changed,now=2.5),(NAMES[0],'',NAMES[2]))
        self.assertEqual(self.state._counts,(2,0,2))
        # A late positive callback cannot re-seed the erased old title.
        self.assertEqual(self.state.recheck(evidence(),now=2.5),(NAMES[0],'',NAMES[2]))
        self.assertEqual((self.state._last_serial,self.state._last_capture,self.state._last_ocr),stamps)
        self.assertEqual(self.observe(3,rows((NAMES[0],NAMES[3],NAMES[2]))),(NAMES[0],'',NAMES[2]))
        self.assertEqual(self.state._counts,(2,1,2))
        self.assertEqual(self.observe(4,rows((NAMES[0],NAMES[3],NAMES[2]))),(NAMES[0],NAMES[3],NAMES[2]))

    def test_early_recheck_unknown_low_confidence_and_missing_rows(self):
        for lines,expected in ((rows((NAMES[0],'未知强化',NAMES[2])),(NAMES[0],'',NAMES[2])),
                               (rows(scores=(.99,.92,.99)),(NAMES[0],'',NAMES[2])),
                               (rows()[:2],EMPTY_SLOTS)):
            self.state=PartialCandidateState();self.stable()
            stamps=(self.state._last_serial,self.state._last_capture,self.state._last_ocr)
            self.assertEqual(self.state.recheck(evidence(lines),now=2.5),expected)
            self.assertEqual((self.state._last_serial,self.state._last_capture,self.state._last_ocr),stamps)

    def test_early_positive_never_promotes_unknown_or_extends_ttl(self):
        partial=rows((NAMES[0],'未知强化',NAMES[2]))
        self.observe(1,partial);self.observe(2,partial)
        for now in (2.5,3.,6.):
            self.assertEqual(self.state.recheck(evidence(),now=now),(NAMES[0],'',NAMES[2]))
            self.assertEqual(self.state._counts,(2,0,2))
        self.assertEqual(self.state.recheck(evidence(),now=6.001),EMPTY_SLOTS)
        self.assertEqual((self.state._last_serial,self.state._last_capture,self.state._last_ocr),(2,2,2))

    def test_two_independent_frames_required_per_known_slot(self):
        partial = rows((NAMES[0], '未知强化', NAMES[2]))
        self.assertEqual(self.observe(1, partial), EMPTY_SLOTS)
        self.assertEqual(self.observe(2, partial), (NAMES[0], '', NAMES[2]))

    def test_changed_slot_blanks_immediately_and_reappears_after_second_frame(self):
        self.stable()
        changed = rows((NAMES[0], NAMES[3], NAMES[2]))
        self.assertEqual(self.observe(3, changed), (NAMES[0], '', NAMES[2]))
        self.assertEqual(self.observe(4, changed), (NAMES[0], NAMES[3], NAMES[2]))

    def test_unknown_or_low_confidence_never_keeps_old_name(self):
        for bad in (rows((NAMES[0], '未知强化', NAMES[2])), rows(scores=(.99, .92, .99))):
            self.state = PartialCandidateState()
            self.stable()
            self.assertEqual(self.observe(3, bad), (NAMES[0], '', NAMES[2]))
            self.assertEqual(self.observe(4), (NAMES[0], '', NAMES[2]))
            self.assertEqual(self.observe(5), NAMES[:3])

    def test_missing_or_ambiguous_geometry_revokes_all_slots(self):
        self.stable()
        self.assertEqual(self.observe(3, rows()[:2]), EMPTY_SLOTS)
        self.assertEqual(self.observe(4), EMPTY_SLOTS)
        self.assertEqual(self.observe(5), NAMES[:3])

    def test_cache_hit_cannot_seed_or_promote_any_slot(self):
        self.assertEqual(self.observe(1, ocr_reused=True), EMPTY_SLOTS)
        self.assertEqual(self.observe(2), EMPTY_SLOTS)
        self.assertEqual(self.observe(3, ocr_reused=True), EMPTY_SLOTS)
        self.assertEqual(self.observe(4), NAMES[:3])

    def test_cache_can_sustain_confirmed_exact_current_names_only(self):
        self.stable()
        self.assertEqual(self.observe(3, ocr_reused=True), NAMES[:3])
        changed = rows((NAMES[0], NAMES[3], NAMES[2]))
        self.assertEqual(self.observe(4, changed, ocr_reused=True), (NAMES[0], '', NAMES[2]))
        self.assertEqual(self.observe(5, changed), (NAMES[0], '', NAMES[2]))
        self.assertEqual(self.observe(6, changed), (NAMES[0], NAMES[3], NAMES[2]))

    def test_cached_frames_do_not_extend_independent_evidence_gap(self):
        self.assertEqual(self.observe(1), EMPTY_SLOTS)
        self.assertEqual(self.observe(2, ocr_reused=True), EMPTY_SLOTS)
        self.assertEqual(self.observe(3, ocr_reused=True), EMPTY_SLOTS)
        self.assertEqual(self.observe(6), EMPTY_SLOTS)
        self.assertEqual(self.observe(7), NAMES[:3])

    def test_focus_occlusion_unknown_hero_and_other_caller_guards_clear(self):
        self.stable()
        self.assertEqual(self.observe(3, guards_passed=False), EMPTY_SLOTS)
        self.assertEqual(self.observe(4), EMPTY_SLOTS)
        self.assertEqual(self.observe(5), NAMES[:3])
        self.state.clear()
        self.assertEqual(self.state.visible(5), EMPTY_SLOTS)
        self.assertEqual(self.observe(6), EMPTY_SLOTS)

    def test_context_change_needs_two_new_frames(self):
        for index in range(len(CONTEXT)):
            self.state = PartialCandidateState()
            self.stable()
            context = list(CONTEXT)
            context[index] = 'changed'
            self.assertEqual(self.observe(3, context=tuple(context)), EMPTY_SLOTS)
            self.assertEqual(self.observe(4, context=tuple(context)), NAMES[:3])

    def test_visible_guard_failure_also_revokes_continuity(self):
        self.stable()
        self.assertEqual(self.state.visible(2, guards_passed=False), EMPTY_SLOTS)
        self.assertEqual(self.state.visible(2), EMPTY_SLOTS)
        self.assertEqual(self.observe(3), EMPTY_SLOTS)

    def test_expired_future_nonfinite_or_boolean_time_fails_closed(self):
        for captured, now in ((2, 6.001), (3, 2), (float('nan'), 2),
                              (2, float('inf')), (True, 2), (2, True), (-1, 0)):
            self.state = PartialCandidateState()
            self.stable()
            self.assertEqual(self.observe(3, captured_at=captured, now=now), EMPTY_SLOTS)
            self.assertEqual(self.state.visible(3), EMPTY_SLOTS)

    def test_four_second_visibility_bound_and_delivery_delay_continuity(self):
        self.stable()
        self.assertEqual(self.state.visible(6), NAMES[:3])
        self.assertEqual(self.state.visible(6.001), EMPTY_SLOTS)
        # A new frame was captured at 5 before the prior display expired, but
        # OCR finished at 8: fresh evidence can still use that capture gap.
        self.assertEqual(self.observe(3, captured_at=5, now=8), NAMES[:3])
        self.assertEqual(self.state.visible(9.001), EMPTY_SLOTS)

    def test_replayed_serial_or_time_never_counts(self):
        self.assertEqual(self.observe(1), EMPTY_SLOTS)
        self.assertEqual(self.observe(1, captured_at=2, now=2), EMPTY_SLOTS)
        self.assertEqual(self.observe(2), EMPTY_SLOTS)
        self.assertEqual(self.observe(3, captured_at=2, now=3), EMPTY_SLOTS)
        self.assertEqual(self.observe(4), EMPTY_SLOTS)
        self.assertEqual(self.observe(5), NAMES[:3])

    def test_clear_keeps_serial_watermark(self):
        self.stable()
        self.state.clear()
        self.assertEqual(self.observe(2), EMPTY_SLOTS)
        self.assertEqual(self.observe(3), EMPTY_SLOTS)

    def test_missing_or_non_boolean_provenance_cannot_count(self):
        for value in (None, 0, 1, 'false'):
            self.state = PartialCandidateState()
            self.assertEqual(self.observe(1, ocr_reused=value), EMPTY_SLOTS)
            self.assertEqual(self.observe(2), EMPTY_SLOTS)
        for value in (None, 1, 'true'):
            self.state = PartialCandidateState()
            self.assertEqual(self.observe(1, guards_passed=value), EMPTY_SLOTS)
            self.assertEqual(self.observe(2), EMPTY_SLOTS)

    def test_several_rounds_keep_positions_and_never_carry_old_tier_name(self):
        self.stable()
        self.assertEqual(self.observe(3, rows((NAMES[2], NAMES[0], NAMES[3]))), EMPTY_SLOTS)
        self.assertEqual(self.observe(4, rows((NAMES[2], NAMES[0], NAMES[3]))),
                         (NAMES[2], NAMES[0], NAMES[3]))
        self.assertEqual(self.observe(5, rows((NAMES[2], '新未知名称', NAMES[1]))),
                         (NAMES[2], '', ''))
        self.assertEqual(self.observe(6, rows((NAMES[2], '新未知名称', NAMES[1]))),
                         (NAMES[2], '', NAMES[1]))


if __name__ == '__main__':
    unittest.main()
