"""Original procedural diagnostic artwork only; not game portraits or assets."""
import io
import numpy as np
from PIL import Image,ImageDraw

def portraits():
    bank={}
    for i in range(6):
        rng=np.random.default_rng(904+i);pixels=rng.integers(20,240,(8,8,3),dtype=np.uint8)
        image=Image.fromarray(pixels).resize((128,128),Image.Resampling.BICUBIC)
        draw=ImageDraw.Draw(image);draw.ellipse((25,28,95,104),outline=(240,30+i*25,130),width=6);draw.line((30,40,90,85),fill=(30,240,90),width=8)
        bank[str(9001+i)]=image
    return bank

def frame(portrait,*,width=1280,height=720,side=False,gray=False):
    image=Image.new('RGB',(width,height),(24,42,62));p=portrait.resize((round(height*.085),)*2,Image.Resampling.LANCZOS)
    if gray:p=p.convert('L').convert('RGB')
    center=(round(width*.91) if side else round(width/2-height*.27),round(height*.94));image.paste(p,(center[0]-p.width//2,center[1]-p.height//2));return image

def encoded(image):
    out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()



def configure_data(data):
    """Diagnostic-only shorter original names for readable small-screen cards."""
    mapping={'星火共鸣（演示）':'星火共鸣','晶盾回路（演示）':'晶盾回路','风步微光（演示）':'风步微光'}
    for old,new in mapping.items():data['augments'][new]=dict(data['augments'][old])
    for rows in data['heroAugmentStats'].values():
        for row in rows:row['augmentName']=mapping.get(row['augmentName'],row['augmentName'])
    data['heroes']['星火术士（演示）']['championId']='9001';data['heroes']['磐石守卫（演示）']['championId']='9002'
    return data
