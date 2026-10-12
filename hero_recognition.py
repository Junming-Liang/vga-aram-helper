"""Local own-HUD portrait matching. No client APIs, screen text hero guessing, or memory.

Initial supported layout: unobstructed, colored base portrait in the standard
bottom HUD left of center, 16:9 through 21:9. Unsupported layouts, death masks,
letterboxing, skins/transform portraits, or low confidence must abstain.
"""
from __future__ import annotations
import io
import math


class PortraitMatcher:
    def __init__(self, portraits, heroes, *, minimum_score=.88, minimum_margin=.07):
        import cv2
        import numpy as np
        cv2.setNumThreads(2)
        self.cv=cv2;self.np=np;self.minimum_score=minimum_score;self.minimum_margin=minimum_margin
        self.names={str(row.get('championId')):name for name,row in heroes.items() if isinstance(row,dict) and str(row.get('championId','')).isdigit()}
        self.templates={}
        for key,image in portraits.items():
            rgb=np.asarray(image.convert('RGB'))
            # Center core excludes circular HUD frame and Data Dragon border.
            h,w=rgb.shape[:2];crop=rgb[round(h*.22):round(h*.78),round(w*.22):round(w*.78)]
            self.templates[str(key)]=(crop,cv2.cvtColor(crop,cv2.COLOR_RGB2GRAY))
    def recognize(self, image_bytes):
        from PIL import Image
        if not isinstance(image_bytes,bytes) or len(image_bytes)>16*1024*1024:return self.unknown('无效截图')
        with Image.open(io.BytesIO(image_bytes)) as image:
            w,h=image.size
            if w*h>16_000_000 or h<600 or not 1.55<=w/h<=2.45:return self.unknown('当前分辨率/纵横比未验证')
            image.load();rgb=self.np.asarray(image.convert('RGB'))
        return self.recognize_array(rgb)
    @staticmethod
    def unknown(reason, **extra):return {'hero':None,'championId':None,'confident':False,'method':'own-hud-portrait','reason':reason,**extra}
    def recognize_array(self,rgb):
        cv=self.cv;np=self.np;h,w=rgb.shape[:2]
        if h<600 or not 1.55<=w/h<=2.45 or not self.templates:return self.unknown('模板或画面比例不可用')
        # Reject hard letterboxes: do not move the ROI to arbitrary champion art.
        if any(np.std(edge)<2 and np.mean(edge)<8 for edge in (rgb[:max(2,h//100)],rgb[-max(2,h//100):],rgb[:,:max(2,w//100)],rgb[:,-max(2,w//100):])):return self.unknown('黑边/画面布局未验证')
        scale=720/h;small=cv.resize(rgb,(round(w*scale),720),interpolation=cv.INTER_AREA);sw=small.shape[1]
        # Own HUD portrait sits left of centered ability bar; excludes sidebars,
        # minimap and scoreboard. Never search the rest of the screenshot.
        x0=max(0,round(sw/2-720*.36));x1=min(sw,round(sw/2-720*.12));y0=round(720*.86);y1=round(720*.995)
        roi=small[y0:y1,x0:x1];gray=cv.cvtColor(roi,cv.COLOR_RGB2GRAY)
        found=[]
        for key,(color,template) in self.templates.items():
            best=(-1,None,None)
            for size in range(20,49,2):
                scaled=cv.resize(template,(size,size),interpolation=cv.INTER_AREA)
                scores=cv.matchTemplate(gray,scaled,cv.TM_CCOEFF_NORMED);_,value,_,location=cv.minMaxLoc(scores)
                if math.isfinite(value) and value>best[0]:best=(value,location,size)
            value,location,size=best
            found.append((value,key,location,size,color))
        found.sort(key=lambda item:item[0],reverse=True)
        if len(found)<2:return self.unknown('模板词典不完整')
        value,key,(x,y),size,color=found[0];second=found[1][0];margin=value-second
        evidence={'score':round(value,4),'margin':round(margin,4),'box':[round((x0+x)/scale),round((y0+y)/scale),round(size/scale),round(size/scale)],'candidateChampionId':key}
        if value<self.minimum_score or margin<self.minimum_margin:return self.unknown('本人头像匹配不够确定',**evidence)
        patch=roi[y:y+size,x:x+size];sat=cv.cvtColor(patch,cv.COLOR_RGB2HSV)[:,:,1]
        if float(np.mean(sat))<22:return self.unknown('灰度/死亡头像不自动确定',**evidence)
        expected=cv.resize(color,(size,size),interpolation=cv.INTER_AREA)
        # Independent color agreement suppresses similar grayscale structures.
        a=patch.astype(np.float32).reshape(-1);b=expected.astype(np.float32).reshape(-1)
        a-=a.mean();b-=b.mean();color_score=float(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)+1e-8));evidence['colorScore']=round(color_score,4)
        if color_score<.75:return self.unknown('头像颜色不匹配或被遮挡',**evidence)
        hero=self.names.get(key)
        if not hero:return self.unknown('头像对应英雄没有当前资料',**evidence)
        return {'hero':hero,'championId':key,'confident':True,'method':'own-hud-portrait','reason':'本人 HUD 头像通过空间与模板校验',**evidence}


def recognize_frame(image_bytes, roi, ocr, vocabulary, matcher=None):
    """Split one same-time selected-window frame in memory. Never persist images."""
    from PIL import Image
    from screen_capture import bounded_roi
    with Image.open(io.BytesIO(image_bytes)) as image:
        if image.width*image.height>16_000_000:raise ValueError('截图尺寸过大')
        image.load();frame_height=image.height;left,top,width,height=bounded_roi(image.width,image.height,roi)
        crop=image.convert('RGB').crop((left,top,left+width,top+height));out=io.BytesIO();crop.save(out,format='PNG')
    hero=matcher.recognize(image_bytes) if matcher else PortraitMatcher.unknown('头像模板尚未准备好')
    result=ocr.recognize(out.getvalue(),vocabulary);result['hero_observation']=hero
    # Automatic titles are constrained to the actual centered card-title band,
    # separate from review suggestions and any unrelated overlay/chat text.
    from local_ocr import candidate_matches
    import unicodedata
    canonical_text={''.join(unicodedata.normalize('NFKC',name).split()) for name in vocabulary}
    title_lines=[]
    for line in result.get('ocr_lines',[]):
        box=line.get('box');text=''.join(unicodedata.normalize('NFKC',str(line.get('text',''))).split())
        if text not in canonical_text or not isinstance(box,list) or len(box)!=4:continue
        try:center_y=top+sum(float(p[1]) for p in box)/4
        except (ValueError,TypeError,IndexError):continue
        if .32*frame_height<=center_y<=.55*frame_height:title_lines.append(line)
    result['automatic_candidates']=candidate_matches(title_lines,vocabulary,min_ocr_confidence=.93)
    return result
