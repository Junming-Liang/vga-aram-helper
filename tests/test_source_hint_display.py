import unittest
from native_state import display_cards
from tests.test_source_combo_hints import fixture

class SourceHintDisplayTests(unittest.TestCase):
    def test_source_hint_follows_original_card_slot_and_keeps_grade_literal(self):
        data=fixture();data['heroAugmentStats']={'英雄甲':[{'augmentName':'强化甲','augmentId':'11','tier':'T3'}]}
        cards=display_cards(data,'英雄甲',['强化丁','强化甲','强化乙'])
        self.assertEqual([c['slot'] for c in cards],[1,2,3])
        self.assertEqual(cards[1]['sourceTier'],'T3')
        self.assertEqual(cards[1]['sourceHint'],'搭配：强化乙、强化丙')
        self.assertEqual(cards[1]['sourceHintProvenance']['kind'],'hero-source-combo-example')
        self.assertNotIn('sourceHint',cards[0])
        self.assertNotIn('winRate',str(cards))
    def test_no_source_combo_does_not_invent_recommendation(self):
        data=fixture();data['heroSourceCombos']={}
        self.assertTrue(all('sourceHint' not in c for c in display_cards(data,'英雄甲',['强化甲'])))

if __name__=='__main__':unittest.main()
