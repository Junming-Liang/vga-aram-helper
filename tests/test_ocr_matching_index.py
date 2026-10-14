"""Exact-first matching and dictionary-cache isolation; no images/models needed."""
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from local_ocr import _name_index, candidate_matches
from native_state import automatic_candidates


def line(text, score=.99, x=100):
    return {'text':text,'confidence':score,'box':[[x,150],[x+80,150],[x+80,180],[x,180]]}


class IndexedMatchingTests(unittest.TestCase):
    def setUp(self):
        _name_index.cache_clear()

    def test_exact_full_title_beats_alphabetically_earlier_contained_name(self):
        result=candidate_matches([line('珠光护手强化')],['珠光护手','珠光护手强化'])
        self.assertEqual([item['name'] for item in result],['珠光护手强化'])
        self.assertEqual(result[0]['match_method'],'exact')

    def test_real_snapshot_prefix_collision_resolves_full_literal_title(self):
        result=candidate_matches([line('无限循环往复')],['循环往复','无限循环往复'])
        self.assertEqual([item['name'] for item in result],['无限循环往复'])
        self.assertEqual(result[0]['match_method'],'exact')

    def test_invalid_box_numbers_still_fail_automatic_gate(self):
        for value in (float('nan'),float('inf'),True,'100'):
            rows=[line('珠光护手'),line('炼狱导管',x=400),line('双刀流',x=700)]
            rows[0]['box'][0][1]=value
            result=candidate_matches(rows,['珠光护手','炼狱导管','双刀流'])
            self.assertFalse(automatic_candidates(result,{'width':900,'height':400}))

    def test_exact_path_never_runs_fuzzy_matching(self):
        with patch('local_ocr.SequenceMatcher',side_effect=AssertionError('Exact needs no fuzzy search')):
            result=candidate_matches([line('珠光护手')],['珠光护手','炼狱导管','双刀流'])
        self.assertEqual(result[0]['name'],'珠光护手')

    def test_unique_contained_match_never_runs_fuzzy_matching(self):
        with patch('local_ocr.SequenceMatcher',side_effect=AssertionError('Containment needs no fuzzy search')):
            result=candidate_matches([line('选择珠光护手')],['珠光护手','炼狱导管'])
        self.assertEqual(result[0]['match_method'],'contained-name')
        self.assertTrue(result[0]['requires_confirmation'])

    def test_multiple_contained_names_abstain_in_both_dictionary_orders(self):
        for names in (['珠光护手','珠光护手强化'],['珠光护手强化','珠光护手']):
            self.assertEqual(candidate_matches([line('选择珠光护手强化')],names),[])

    def test_normalized_collision_uses_only_unique_literal_spelling(self):
        names=['珠光护手','珠光·护手']
        for spelling in names:
            with self.subTest(spelling=spelling):
                result=candidate_matches([line(spelling)],names)
                self.assertEqual([item['name'] for item in result],[spelling])
                self.assertEqual(result[0]['match_method'],'exact')

    def test_normalized_collision_without_literal_spelling_abstains(self):
        self.assertEqual(candidate_matches([line('【珠光护手】')],['珠光护手','珠光·护手']),[])

    def test_multiple_literal_equivalents_abstain(self):
        self.assertEqual(candidate_matches([line('珠光护手')],['珠光护手','珠光 护手']),[])

    def test_duplicate_vocabulary_entries_do_not_create_fuzzy_ambiguity(self):
        result=candidate_matches([line('星火共鸣演式')],['星火共鸣演示','星火共鸣演示'])
        self.assertEqual(result[0]['match_method'],'fuzzy-suggestion')
        self.assertTrue(result[0]['requires_confirmation'])

    def test_mutated_dictionary_cannot_reuse_removed_name(self):
        names={'珠光护手':{}}
        self.assertEqual(candidate_matches([line('珠光护手')],names)[0]['name'],'珠光护手')
        names.clear();names['炼狱导管']={}
        self.assertEqual(candidate_matches([line('珠光护手')],names),[])
        self.assertEqual(candidate_matches([line('炼狱导管')],names)[0]['name'],'炼狱导管')

    def test_cache_stores_names_only_not_result_confidence_or_position(self):
        first=candidate_matches([line('珠光护手',.99,100)],['珠光护手'])
        first[0]['name']='modified caller result'
        result=candidate_matches([line('珠光护手',.70,400)],['珠光护手'])
        self.assertEqual(result[0]['name'],'珠光护手')
        self.assertEqual(result[0]['ocr_confidence'],.70)
        self.assertEqual(result[0]['box'][0],[400,150])
        self.assertEqual(candidate_matches([line('珠光护手',.50)],['珠光护手']),[])

    def test_cache_is_bounded_across_vocabulary_changes(self):
        for i in range(8):
            name='海克斯'+str(i)
            self.assertEqual(candidate_matches([line(name)],[name])[0]['name'],name)
        self.assertEqual(_name_index.cache_info().currsize,4)

    def test_dictionary_index_reused_for_equal_content(self):
        candidate_matches([line('珠光护手')],['珠光护手','炼狱导管'])
        candidate_matches([line('炼狱导管')],{'珠光护手':{},'炼狱导管':{}})
        info=_name_index.cache_info()
        self.assertEqual((info.misses,info.hits),(1,1))

    def test_parallel_dictionaries_remain_isolated(self):
        names=['珠光护手','炼狱导管','双刀流']*6
        def match(name):
            return candidate_matches([line(name)],[name])[0]['name']
        with ThreadPoolExecutor(max_workers=3) as pool:
            self.assertEqual(list(pool.map(match,names)),names)

    def test_review_suggestions_cannot_pass_automatic_gate(self):
        for text,method in [('选择珠光护手','contained-name'),('星火共鸣演式','fuzzy-suggestion')]:
            result=candidate_matches([line(text),line('炼狱导管',x=400),line('双刀流',x=700)],
                                     ['珠光护手','星火共鸣演示','炼狱导管','双刀流'])
            self.assertEqual(len(result),3)
            self.assertEqual(result[0]['match_method'],method)
            self.assertFalse(automatic_candidates(result,{'width':900,'height':400}))


if __name__=='__main__':unittest.main()
