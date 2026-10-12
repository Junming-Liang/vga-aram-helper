"""Experimental screenshot-only ARAM assigned-champion text detector.

No window/process APIs here. Caller supplies only an explicitly permitted client
frame. Gold-row emphasis is an empirical UI anchor, not a Riot API guarantee.
Unknown layouts, candidate-card phase and inconsistent ownership abstain.
"""
from __future__ import annotations
import io
import math
import re
import unicodedata


def canonical_text(value):
    return ''.join(unicodedata.normalize('NFKC',str(value)).casefold().split())


class ChampionSelectDetector:
    def __init__(self,aliases,ocr):
        """aliases: canonical champion-ID -> verified locale names/titles."""
        self.ocr=ocr;self.aliases={};ambiguous=set()
        for champion_id,names in aliases.items():
            for name in names:
                key=canonical_text(name)
                if not key:continue
                if key in self.aliases and self.aliases[key]!=str(champion_id):ambiguous.add(key)
                self.aliases[key]=str(champion_id)
        for key in ambiguous:self.aliases.pop(key,None)
    @staticmethod
    def unknown(reason,**extra):return {'scene':'unknown','championId':None,'assigned':False,'reason':reason,**extra}
    def recognize(self,payload):
        from PIL import Image
        import numpy as np
        if not isinstance(payload,bytes) or not 0<len(payload)<=16*1024*1024:return self.unknown('Invalid permitted client frame')
        with Image.open(io.BytesIO(payload)) as image:
            w,h=image.size
            if w*h>12_000_000 or w<640 or h<360 or not 1.6<=w/h<=1.9:return self.unknown('Client geometry not supported')
            image.load();image=image.convert('RGB');rgb=np.asarray(image)
        def read(roi):
            x,y,ww,hh=roi;left,top=round(w*x),round(h*y);right,bottom=round(w*(x+ww)),round(h*(y+hh))
            crop=image.crop((left,top,right,bottom));out=io.BytesIO();crop.save(out,format='PNG')
            result=self.ocr.recognize(out.getvalue(),[])
            return result.get('ocr_lines',[]),(left,top,right-left,bottom-top)
        lines,origin=read((.075,.115,.20,.60))
        observations=[]
        for line in lines:
            champion=self.aliases.get(canonical_text(line.get('text','')))
            confidence=line.get('confidence',0);box=line.get('box')
            if not champion or not isinstance(confidence,(int,float)) or not math.isfinite(confidence) or isinstance(confidence,bool) or not .94<=confidence<=1:continue
            rect=text_box(box,origin,w,h)
            if rect is None:continue
            left,top,right,bottom=rect;center=(top+bottom)/2/h
            # Canonical champion-name line, not the summoner-name line below it.
            possible=[i for i in range(5) if .155+i*.112<=center<=.193+i*.112]
            if len(possible)!=1:continue
            gold=gold_fraction(rgb[top:bottom,left:right])
            if gold<.10:continue
            observations.append({'championId':champion,'row':possible[0]+1,'confidence':confidence,'goldFraction':round(gold,4),'box':list(rect)})
        if len(observations)!=1:return self.unknown('Own highlighted champion-name row absent or ambiguous',ownRowCandidates=len(observations))
        center_lines,center_origin=read((.35,.57,.30,.13))
        center=[]
        for line in center_lines:
            name=self.aliases.get(canonical_text(line.get('text','')));confidence=line.get('confidence',0)
            if name and isinstance(confidence,(int,float)) and math.isfinite(confidence) and not isinstance(confidence,bool) and .94<=confidence<=1:
                box=text_box(line.get('box'),center_origin,w,h)
                if box is not None:center.append({'championId':name,'confidence':confidence,'box':box})
        skin_boxes=skin_selector_boxes(rgb)
        if len(center)!=1 or center[0]['championId']!=observations[0]['championId'] or len(skin_boxes)<3:
            return self.unknown('Current own row, central name and post-choice skin selector do not agree',ownRow=observations[0],centerCandidates=center,skinSelectorBoxes=skin_boxes)
        return {'scene':'assigned-selection','championId':observations[0]['championId'],'assigned':True,'reason':'Own highlighted row and central champion name agree in post-choice scene; current assignment, not an irrevocable lock','ownRow':observations[0],'center':center[0],'skinSelectorBoxes':skin_boxes,'method':'client-own-row-and-center-ocr','requiresTemporalStability':True}


def text_box(box,origin,w,h):
    if not isinstance(box,list) or len(box)!=4:return None
    try:
        values=[float(v) for point in box for v in point]
        if len(values)!=8 or not all(math.isfinite(v) for v in values):return None
        xs=values[::2];ys=values[1::2]
        if min(xs)<0 or min(ys)<0 or max(xs)>origin[2] or max(ys)>origin[3]:return None
        left=max(0,int(min(xs)+origin[0]));top=max(0,int(min(ys)+origin[1]));right=min(w,math.ceil(max(xs)+origin[0]));bottom=min(h,math.ceil(max(ys)+origin[1]))
        return (left,top,right,bottom) if right>left and bottom>top else None
    except (TypeError,ValueError):return None


def gold_fraction(patch):
    import cv2
    import numpy as np
    if not patch.size:return 0.
    hsv=cv2.cvtColor(patch,cv2.COLOR_RGB2HSV)
    return float(np.mean((hsv[:,:,0]>=15)&(hsv[:,:,0]<=38)&(hsv[:,:,1]>=95)&(hsv[:,:,2]>=120)))


def skin_selector_boxes(rgb):
    """Require several small thumbnail outlines, not large initial choice cards."""
    import cv2
    h,w=rgb.shape[:2];left,top=round(w*.27),round(h*.69);crop=rgb[top:round(h*.84),left:round(w*.73)]
    edges=cv2.Canny(cv2.cvtColor(crop,cv2.COLOR_RGB2GRAY),35,100);contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    boxes=[]
    for contour in contours:
        x,y,ww,hh=cv2.boundingRect(contour)
        if not .035*w<=ww<=.105*w or not .045*h<=hh<=.13*h or not .7<=ww/hh<=1.9:continue
        if any(abs((x+ww/2)-(a+c/2))<.02*w for a,b,c,d in boxes):continue
        boxes.append((x,y,ww,hh))
    if not boxes:return []
    # Thumbnails must form one horizontally aligned row.
    best=max(([b for b in boxes if abs((b[1]+b[3]/2)-(anchor[1]+anchor[3]/2))<.025*h] for anchor in boxes),key=len)
    return [[x+left,y+top,ww,hh] for x,y,ww,hh in sorted(best)]
