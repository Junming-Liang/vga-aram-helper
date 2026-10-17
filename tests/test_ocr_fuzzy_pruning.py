"""Safe upper-bound pruning parity; no OCR model or screenshot assumptions."""
from difflib import SequenceMatcher
import random
import unittest
from unittest.mock import patch

from local_ocr import _match_name, _name_index, candidate_matches, normalized_name


def legacy_fuzzy(cleaned, dictionary):
    ranked=[(SequenceMatcher(None,cleaned,value).ratio(),name,'fuzzy-suggestion')
            for name,value in dictionary]
    ranked.sort(key=lambda row:(-row[0],row[1]))
    if not ranked or ranked[0][0]<.78:return None
    if len(ranked)>1 and ranked[0][0]-ranked[1][0]<.1:return None
    return ranked[0]


class FuzzyPruningTests(unittest.TestCase):
    def test_seeded_fuzzy_results_match_unpruned_reference(self):
        rng=random.Random(227)
        alphabet='abcdefghijk珠光护手炼狱导管'
        checked=0
        for _ in range(600):
            text=''.join(rng.choices(alphabet,k=rng.randrange(2,40)))
            names=[''.join(rng.choices(alphabet,k=rng.randrange(2,35))) for _ in range(20)]
            # Include plausible winning/margin-sensitive OCR errors.
            names += [text[:-1]+rng.choice(alphabet),text[:-2]+rng.choice(alphabet)*2]
            dictionary,exact=_name_index(tuple(names))
            cleaned=normalized_name(text)
            if cleaned in exact or any(len(value)>=3 and value in cleaned and len(cleaned)<=len(value)+8 for _,value in dictionary):
                continue
            self.assertEqual(_match_name(text,cleaned,dictionary,exact),legacy_fuzzy(cleaned,dictionary))
            checked+=1
        self.assertGreater(checked,500)

    def test_long_description_skips_matcher_construction(self):
        with patch('local_ocr.SequenceMatcher',side_effect=AssertionError('Length bound should prune')):
            result=candidate_matches([{'text':'unrelateddescription'*20,'confidence':.99}],['珠光护手','炼狱导管'])
        self.assertEqual(result,[])

    def test_runner_up_below_acceptance_still_blocks_ambiguous_winner(self):
        # .8 winner and .777 runner-up: neither may be pruned at .78.
        dictionary=(('winner','abcdefghij'),('runner','abcdefgx'))
        text='abcdefghzz'
        self.assertIsNone(legacy_fuzzy(text,dictionary))
        self.assertEqual(_match_name(text,text,dictionary,{}),legacy_fuzzy(text,dictionary))


if __name__=='__main__':unittest.main()
