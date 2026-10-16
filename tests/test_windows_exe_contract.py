"""Portable checks of the actual frozen-EXE acceptance contract, no EXE mock claim."""
import copy
import json
from pathlib import Path
import unittest

from engine import normalize
from public_payload import public_comparison
from tests.windows_exe_smoke import (assert_grade_only_comparison, DEMO_OFFERED,
    DEMO_HERO_GRADES, FORBIDDEN_PUBLIC_FIELDS)


class FrozenComparisonContractTests(unittest.TestCase):
    def setUp(self):
        self.data = normalize(json.loads((Path(__file__).resolve().parents[1] / 'fixtures/demo.json').read_text()))
        self.hero = next(iter(DEMO_HERO_GRADES))
        self.result = public_comparison(self.data, self.hero, list(DEMO_OFFERED))

    def check(self, result):
        assert_grade_only_comparison(result, self.hero, DEMO_OFFERED, DEMO_HERO_GRADES[self.hero])

    def test_both_heroes_preserve_slots_with_different_literal_grades(self):
        for hero, grades in DEMO_HERO_GRADES.items():
            with self.subTest(hero=hero):
                assert_grade_only_comparison(public_comparison(self.data, hero, list(DEMO_OFFERED)), hero, DEMO_OFFERED, grades)

    def test_rejects_every_removed_public_field_at_root_and_nested(self):
        for field in FORBIDDEN_PUBLIC_FIELDS:
            for nested in (False, True):
                with self.subTest(field=field, nested=nested):
                    result = copy.deepcopy(self.result)
                    (result['cards'][0] if nested else result)[field] = None
                    with self.assertRaises(AssertionError): self.check(result)

    def test_rejects_wrong_hero_slot_name_grade_order_and_count(self):
        for change in (
            lambda r: r.update(hero='other'),
            lambda r: r.update(policy='old'),
            lambda r: r['offered'].reverse(),
            lambda r: r['cards'].reverse(),
            lambda r: r['cards'].pop(),
            lambda r: r['cards'][0].update(slot=2),
            lambda r: r['cards'][0].update(name='other'),
            lambda r: r['cards'][0].update(sourceTier='T4'),
            lambda r: r['cards'][0].update(sourceTier=None),
        ):
            result = copy.deepcopy(self.result); change(result)
            with self.assertRaises(AssertionError): self.check(result)

    def test_missing_required_grade_is_not_silently_accepted(self):
        del self.result['cards'][0]['sourceTier']
        with self.assertRaises(KeyError): self.check(self.result)



class BrowserContractTests(unittest.TestCase):
    def test_dom_contract_rejects_preferred_wrong_slot_grade_and_rate_text(self):
        from tests.windows_exe_smoke import assert_grade_only_browser
        class Node:
            def __init__(self, value): self.value = value
            def nth(self, index): return Node(self.value[index])
            def locator(self, selector): return Node(self.value[selector])
            def inner_text(self): return self.value
            def to_have_count(self, count): assert len(self.value) == count
            def to_have_text(self, text): assert self.value == text
        class Page:
            def __init__(self):
                self.nodes = {
                    '.comparison-card': [dict(zip(('h3', '.card-top .badge', ':scope > .badge'),
                        (name, f'原选项 {index + 1}', f'源评级 {grade}')))
                        for index, (name, grade) in enumerate(zip(DEMO_OFFERED, ('T1','T2','T3')))],
                    '.comparison-card.preferred': [], '#choice-result': '原始评级'}
            def locator(self, selector): return Node(self.nodes[selector])
        def check(page): assert_grade_only_browser(page, lambda node: node, DEMO_OFFERED, ('T1','T2','T3'))
        check(Page())
        for mutate in (
            lambda p: p.nodes['.comparison-card'].reverse(),
            lambda p: p.nodes['.comparison-card'][0].update({'h3':'other'}),
            lambda p: p.nodes['.comparison-card'][0].update({'.card-top .badge':'原选项 2'}),
            lambda p: p.nodes['.comparison-card'][0].update({':scope > .badge':'源评级 T4'}),
            lambda p: p.nodes['.comparison-card.preferred'].append('bad'),
            lambda p: p.nodes.update({'#choice-result':'55.1%'}),
            lambda p: p.nodes.update({'#choice-result':'推荐首选'}),
        ):
            page=Page(); mutate(page)
            with self.assertRaises(AssertionError): check(page)


if __name__ == '__main__': unittest.main()
