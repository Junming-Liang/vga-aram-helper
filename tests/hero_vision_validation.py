"""Original procedural portrait tests; never genuine League accuracy evidence."""
import io,json,sys
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from hero_recognition import PortraitMatcher

from synthetic_vision import portraits,frame,encoded

if __name__=='__main__':
    bank=portraits();matcher=PortraitMatcher(bank,{f'虚构英雄{i}':{'championId':str(9001+i)} for i in range(6)});checks=[]
    for width,height in [(1280,720),(1920,1080),(2560,1440),(3440,1440)]:
        result=matcher.recognize(encoded(frame(bank['9001'],width=width,height=height)));assert result['championId']=='9001',(width,result);checks.append(f'Original synthetic ownHUD at {width}x{height} recognized')
    for image,scope in [(frame(bank['9001'],side=True),'sidebar'),(frame(bank['9001'],gray=True),'grayscale death analogue'),(Image.new('RGB',(1280,720),(20,30,40)),'blank scene'),(frame(bank['9001'],width=900,height=1200),'portrait crop')]:
        result=matcher.recognize(encoded(image));assert result['hero'] is None,(scope,result);checks.append(scope+' abstains')
    print(json.dumps({'status':'passed','scope':'Original procedural fixtures only, not game accuracy','checks':checks},ensure_ascii=False,indent=2))
