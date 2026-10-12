import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from champion_select import ChampionSelectDetector,text_box,canonical_text
ROOT=Path(__file__).resolve().parents[1]
class OCR:
 def __init__(self,left,center):self.lines=[left,center]
 def recognize(self,*args):return {'ocr_lines':self.lines.pop(0)}
def line(text='星火术士',confidence=.99,box=None):
 return {'text':text,'confidence':confidence,'box':box or [[20,350],[100,350],[100,373],[20,373]]}
class DetectorTests(unittest.TestCase):
 def setUp(self):self.payload=(ROOT/'fixtures/champselect-synthetic.png').read_bytes()
 def detect(self,left=None,center=None):
  ocr=OCR(left if left is not None else [line()],center if center is not None else [line(box=[[20,30],[100,30],[100,55],[20,55]])])
  with patch('champion_select.gold_fraction',return_value=.3),patch('champion_select.skin_selector_boxes',return_value=[[1,1,5,5]]*3):return ChampionSelectDetector({'9001':['星火术士'],'9002':['磐石守卫']},ocr).recognize(self.payload)
 def test_own_fifth_row_and_center_match(self):self.assertTrue(self.detect()['assigned']);self.assertEqual(self.detect()['ownRow']['row'],5)
 def test_center_hover_other_hero_rejected(self):self.assertFalse(self.detect(center=[line('磐石守卫')])['assigned'])
 def test_duplicate_highlighted_rows_rejected(self):self.assertFalse(self.detect(left=[line(),line()])['assigned'])
 def test_nickname_line_not_own_champion(self):self.assertFalse(self.detect(left=[line(box=[[20,388],[100,388],[100,398],[20,398]])])['assigned'])
 def test_bad_center_box_never_qualifies(self):
  row=line();row['box']=None;self.assertFalse(self.detect(center=[row])['assigned'])
 def test_unknown_and_low_confidence_rejected(self):
  for confidence in [.93,float('nan'),True,1.1]:self.assertFalse(self.detect(left=[line(confidence=confidence)])['assigned'])
 def test_no_own_or_initial_cards_rejected(self):self.assertFalse(self.detect(left=[])['assigned'])
 def test_ambiguous_alias_is_removed(self):self.assertNotIn('same',ChampionSelectDetector({'1':['Same'],'2':['same']},None).aliases)
 def test_white_row_does_not_qualify(self):
  with patch("champion_select.gold_fraction",return_value=0):
   result=ChampionSelectDetector({"9001":["星火术士"]},OCR([line()],[])).recognize(self.payload)
  self.assertFalse(result["assigned"])
 def test_no_postchoice_thumbnails_does_not_qualify(self):
  with patch("champion_select.gold_fraction",return_value=.3),patch("champion_select.skin_selector_boxes",return_value=[]):
   result=ChampionSelectDetector({"9001":["星火术士"]},OCR([line()],[line(box=[[20,30],[100,30],[100,55],[20,55]])])).recognize(self.payload)
  self.assertFalse(result["assigned"])
 def test_bad_geometry_and_payload(self):
  detector=ChampionSelectDetector({},None)
  for value in [None,b'',b'x'*(16*1024*1024+1)]:self.assertFalse(detector.recognize(value)['assigned'])
 def test_text_box_bounds(self):
  for value in [None,[],[[0,0]]*3,[[0,float('inf')]]*4,[[1000,1]]*4]:self.assertIsNone(text_box(value,(0,0,20,20),100,100))
 def test_canonical_text(self):self.assertEqual(canonical_text(' Aｂ C '),'abc')
if __name__=='__main__':unittest.main()
