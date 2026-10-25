"""Local own-HUD portrait matching. No client APIs, screen text hero guessing, or memory.

Initial supported layout: unobstructed, colored base portrait in the standard
bottom HUD left of center, 16:9 through 21:9. Unsupported layouts, death masks,
letterboxing, skins/transform portraits, or low confidence must abstain.
"""
from __future__ import annotations
import io
import hashlib
import math
import struct
import time
from dataclasses import dataclass
from types import MappingProxyType


HUD_OUTCOMES = frozenset({'recognized', 'invalid_image', 'unsupported_layout',
    'letterboxed', 'templates_unavailable', 'incomplete_templates', 'score_low',
    'margin_low', 'death_grayscale', 'color_mismatch', 'champion_unmapped', 'unknown'})


def hud_identity_outcome(observation):
    """Only a fixed code; never expose a reason, candidate, or portrait pixels."""
    if not isinstance(observation, dict):return 'unknown'
    outcome = observation.get('hudOutcome')
    if type(outcome) is str and outcome in HUD_OUTCOMES:return outcome
    return 'recognized' if observation.get('confident') is True else 'unknown'


@dataclass(frozen=True)
class _PortraitInput:
    """Per-call normalized HUD pixels; never retained on the matcher."""
    rgb: object
    gray: object
    scale: float
    x0: int
    y0: int
    signature: str


class PortraitMatcher:
    def __init__(self, portraits, heroes, *, minimum_score=.88, minimum_margin=.07):
        import cv2
        import numpy as np
        cv2.setNumThreads(2)
        self.cv=cv2;self.np=np;self.minimum_score=minimum_score;self.minimum_margin=minimum_margin
        self._names=MappingProxyType({str(row.get('championId')):name for name,row in heroes.items() if isinstance(row,dict) and str(row.get('championId','')).isdigit()})
        templates={};scales={}
        for key,image in portraits.items():
            rgb=np.asarray(image.convert('RGB'))
            # Center core excludes circular HUD frame and Data Dragon border.
            h,w=rgb.shape[:2];crop=rgb[round(h*.22):round(h*.78),round(w*.22):round(w*.78)]
            gray=cv2.cvtColor(crop,cv2.COLOR_RGB2GRAY);crop.setflags(write=False);gray.setflags(write=False)
            templates[str(key)]=(crop,gray)
            # The exact same 15 grayscale scales are immutable model inputs,
            # independent of captured pixels. Prepare once; every uncached
            # input still searches all templates/scales with unchanged scoring.
            variants=[]
            for size in range(20,49,2):
                pixels=cv2.resize(gray,(size,size),interpolation=cv2.INTER_AREA);pixels.setflags(write=False);variants.append((size,pixels))
            scales[str(key)]=tuple(variants)
        self._templates=MappingProxyType(templates);self._template_scales=MappingProxyType(scales);self._model_token=object()
        # One deterministic search result, not an identity observation. Keep no
        # screenshot/ROI or frame timestamp. Fresh preparation and every final
        # confidence/color/name gate still run for each independently captured
        # frame. Only the exact built-in immutable model may use this cache.
        self._search_cache=None
    @property
    def names(self):return self._names
    @property
    def templates(self):return self._templates
    @property
    def _scaled_templates(self):return self._template_scales
    def proof_identity(self):
        """Bind immutable per-instance models/names and current thresholds."""
        return self._model_token,self.minimum_score,self.minimum_margin
    def recognize(self, image_bytes):
        return self._recognize_prepared(self._prepare_image(image_bytes))
    def _prepare_image(self,image_bytes,*,decoded_rgb=None):
        from PIL import Image
        if not isinstance(image_bytes,bytes) or len(image_bytes)>16*1024*1024:return self.unknown('无效截图',hudOutcome='invalid_image')
        if decoded_rgb is not None:
            h,w=decoded_rgb.shape[:2]
            if w*h>16_000_000 or h<600 or not 1.55<=w/h<=2.45:return self.unknown('当前分辨率/纵横比未验证',hudOutcome='unsupported_layout')
            return self._prepare_array(decoded_rgb)
        with Image.open(io.BytesIO(image_bytes)) as image:
            w,h=image.size
            if w*h>16_000_000 or h<600 or not 1.55<=w/h<=2.45:return self.unknown('当前分辨率/纵横比未验证',hudOutcome='unsupported_layout')
            image.load();rgb=self.np.asarray(image.convert('RGB'))
        return self._prepare_array(rgb)
    @staticmethod
    def unknown(reason, **extra):return {'hero':None,'championId':None,'confident':False,'method':'own-hud-portrait','reason':reason,**extra}
    def recognize_array(self,rgb):
        return self._recognize_prepared(self._prepare_array(rgb))
    def _prepare_array(self,rgb):
        cv=self.cv;np=self.np;h,w=rgb.shape[:2]
        if h<600 or not 1.55<=w/h<=2.45 or not self.templates:return self.unknown('模板或画面比例不可用',abstentionKind='unsupported-layout',hudOutcome='unsupported_layout' if h<600 or not 1.55<=w/h<=2.45 else 'templates_unavailable')
        # Reject hard letterboxes: do not move the ROI to arbitrary champion art.
        if any(np.std(edge)<2 and np.mean(edge)<8 for edge in (rgb[:max(2,h//100)],rgb[-max(2,h//100):],rgb[:,:max(2,w//100)],rgb[:,-max(2,w//100):])):return self.unknown('黑边/画面布局未验证',abstentionKind='unsupported-layout',hudOutcome='letterboxed')
        scale=720/h;small=cv.resize(rgb,(round(w*scale),720),interpolation=cv.INTER_AREA);sw=small.shape[1]
        # Own HUD portrait sits left of centered ability bar; excludes sidebars,
        # minimap and scoreboard. Never search the rest of the screenshot.
        x0=max(0,round(sw/2-720*.36));x1=min(sw,round(sw/2-720*.12));y0=round(720*.86);y1=round(720*.995)
        roi=small[y0:y1,x0:x1];gray=cv.cvtColor(roi,cv.COLOR_RGB2GRAY)
        # All frame-dependent matcher inputs: validated layout, source and
        # normalized dimensions, coordinates/scale, and the ENTIRE RGB search
        # ROI (including color gates). Template/threshold identity is bound by
        # the caller. Changed edge pixels matter only if a layout gate changes.
        signature=hashlib.sha256(b'vga-own-hud-input-v1\0layout-valid\0')
        signature.update(struct.pack('<8Id',w,h,sw,720,x0,x1,y0,y1,scale))
        signature.update(roi.dtype.str.encode('ascii')+b'\0');signature.update(roi.tobytes())
        return _PortraitInput(roi,gray,scale,x0,y0,signature.hexdigest())
    def _recognize_prepared(self,prepared):
        if isinstance(prepared,dict):return prepared
        cv=self.cv;np=self.np;roi=prepared.rgb;gray=prepared.gray
        scale,x0,y0=prepared.scale,prepared.x0,prepared.y0
        found=self._search_portraits(prepared)
        if len(found)<2:return self.unknown('模板词典不完整',hudOutcome='incomplete_templates')
        value,key,(x,y),size,color=found[0];second=found[1][0];margin=value-second
        evidence={'score':round(value,4),'margin':round(margin,4),'box':[round((x0+x)/scale),round((y0+y)/scale),round(size/scale),round(size/scale)],'candidateChampionId':key}
        if value<self.minimum_score or margin<self.minimum_margin:return self.unknown('本人头像匹配不够确定',abstentionKind='portrait-unavailable',hudOutcome='score_low' if value<self.minimum_score else 'margin_low',**evidence)
        patch=roi[y:y+size,x:x+size];sat=cv.cvtColor(patch,cv.COLOR_RGB2HSV)[:,:,1]
        if float(np.mean(sat))<22:return self.unknown('灰度/死亡头像不自动确定',occlusionKind='death-portrait',abstentionKind='portrait-unavailable',hudOutcome='death_grayscale',**evidence)
        expected=cv.resize(color,(size,size),interpolation=cv.INTER_AREA)
        # Independent color agreement suppresses similar grayscale structures.
        a=patch.astype(np.float32).reshape(-1);b=expected.astype(np.float32).reshape(-1)
        a-=a.mean();b-=b.mean();color_score=float(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)+1e-8));evidence['colorScore']=round(color_score,4)
        if color_score<.75:return self.unknown('头像颜色不匹配或被遮挡',abstentionKind='portrait-unavailable',hudOutcome='color_mismatch',**evidence)
        hero=self.names.get(key)
        if not hero:return self.unknown('头像对应英雄没有当前资料',hudOutcome='champion_unmapped',**evidence)
        return {'hero':hero,'championId':key,'confident':True,'method':'own-hud-portrait','reason':'本人 HUD 头像通过空间与模板校验','hudOutcome':'recognized',**evidence}
    def _search_portraits(self,prepared):
        """Memoize only exhaustive scores for exactly equal validated inputs.

        The digest comes from this frame's full normalized RGB search ROI plus
        layout/dimensions, after fresh letterbox checks. Model and thresholds
        are additionally bound, and subclass search/model overrides never hit.
        A hit cannot bypass current color gates, create a frame, renew a TTL,
        count an OCR confirmation or carry identity between game sessions.
        """
        search_key=(self.proof_identity(),prepared.signature)
        cached=self._search_cache if type(self) is PortraitMatcher else None
        if cached is not None and cached[0]==search_key:return cached[1]
        cv=self.cv;gray=prepared.gray
        found=[]
        for key,(color,template) in self.templates.items():
            best=(-1,None,None)
            for size,scaled in self._scaled_templates[key]:
                scores=cv.matchTemplate(gray,scaled,cv.TM_CCOEFF_NORMED);_,value,_,location=cv.minMaxLoc(scores)
                if math.isfinite(value) and value>best[0]:best=(value,location,size)
            value,location,size=best
            found.append((value,key,location,size,color))
        found.sort(key=lambda item:item[0],reverse=True)
        top=tuple(found[:2])
        if type(self) is PortraitMatcher:self._search_cache=(search_key,top)
        return top


def recognize_frame(image_bytes, roi, ocr, vocabulary, matcher=None, *, before_match=None, before_ocr=None, inference_worker=None, resolve_hero=None, prior_card_geometry=None, prepared_frame=None, diagnostic_callback=None, after_titles=None):
    """Split one same-time selected-window frame in memory. Never persist images."""
    def diagnostic(stage, phase, elapsed_ms=0.):
        # Only bounded stage names/timing, never screenshots or recognized text.
        # OCR can run on a worker: callers must provide a thread-safe logger.
        if diagnostic_callback is not None:
            try:diagnostic_callback(stage,phase,elapsed_ms)
            except Exception:pass
    def begin(stage):
        diagnostic(stage,'started')
        return time.perf_counter()
    def complete(stage, before):
        diagnostic(stage,'completed',(time.perf_counter()-before)*1000)
    def timed_ocr(method, *args):
        before=begin('ocr')
        try:return method(*args)
        finally:complete('ocr',before)
    started=begin('total')
    prepare_started=begin('prepare')
    from PIL import Image
    from screen_capture import bounded_roi
    with Image.open(io.BytesIO(image_bytes)) as image:
        if image.width*image.height>16_000_000:raise ValueError('截图尺寸过大')
        image.load();frame_height=image.height;left,top,width,height=bounded_roi(image.width,image.height,roi)
        rgb=image.convert('RGB');crop=rgb.crop((left,top,left+width,top+height));out=io.BytesIO();crop.save(out,format='PNG')
    crop_bytes=out.getvalue()
    if prepared_frame is not None:prepared_frame(rgb)
    complete('prepare',prepare_started)
    def recognize_titles(method):
        result=timed_ocr(method,crop_bytes,vocabulary)
        phase_started=begin('title_geometry')
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
        # Keep raw unknown/low-confidence title rows for independent fixed-slot
        # evidence. Dictionary candidates alone cannot prove a third card exists.
        from partial_candidates import title_evidence
        result['partial_title_evidence']=title_evidence(result.get('ocr_lines'),result.get('image_size'),vocabulary,crop_top=top,frame_height=frame_height)
        from augment_card_geometry import refresh_frame_card_geometry
        title_geometry=result['partial_title_evidence']
        anchors=title_geometry.slots if title_geometry.valid else result['automatic_candidates']
        result['_cardGeometry']=refresh_frame_card_geometry(image_bytes,prior_card_geometry,anchors,result.get('image_size'),roi,_decoded_rgb=rgb)
        complete('title_geometry',phase_started)
        # This phase may run on the OCR worker. It can revoke stale titles,
        # but never authorizes hero identity or a new observation by itself.
        if after_titles is not None and result.get('ocr_reused') is not True:after_titles(result)
        return result
    # The two independent inferences use the same immutable captured frame.
    # Join both before returning: no next capture overlaps an unfinished worker.
    # A proof callback still runs on the caller, after full HUD validation.
    if type(matcher) is PortraitMatcher:
        phase_started=begin('hud_prepare')
        prepared=matcher._prepare_image(image_bytes,decoded_rgb=matcher.np.asarray(rgb))
        complete('hud_prepare',phase_started)
        if before_match is not None:before_match(prepared.signature if isinstance(prepared,_PortraitInput) else None,crop_bytes)
        pending=inference_worker.submit(recognize_titles,ocr.recognize) if inference_worker is not None else None
        try:
            phase_started=begin('hud_match')
            hero=matcher._recognize_prepared(prepared)
            complete('hud_match',phase_started)
            if resolve_hero is not None:
                phase_started=begin('hero_resolve')
                hero=resolve_hero(hero)
                complete('hero_resolve',phase_started)
            if before_ocr is not None:before_ocr(hero,crop_bytes)
        finally:
            # Also drain on cancellation/proof failure. A native OCR call is not
            # safely interruptible; it may never leak into the next frame.
            if pending is not None:
                result=pending.result()
        if pending is None:result=recognize_titles(ocr.recognize)
    else:
        if before_match is not None:before_match(None,crop_bytes)
        # Missing/loading portrait templates must not serialize the independent
        # title OCR behind the local identity API. Reuse the same single bounded
        # worker as the prepared-matcher path, with the same join on all exits.
        pending=inference_worker.submit(recognize_titles,ocr.recognize) if inference_worker is not None else None
        try:
            phase_started=begin('hud_match')
            hero=matcher.recognize(image_bytes) if matcher else PortraitMatcher.unknown('头像模板尚未准备好',hudOutcome='templates_unavailable')
            complete('hud_match',phase_started)
            if resolve_hero is not None:
                phase_started=begin('hero_resolve')
                hero=resolve_hero(hero)
                complete('hero_resolve',phase_started)
            if before_ocr is not None:before_ocr(hero,crop_bytes)
        finally:
            if pending is not None:result=pending.result()
        if pending is None:result=recognize_titles(ocr.recognize)
    # A title cache hit can race the fresh HUD inference. Unknown current HUD
    # must obtain independent OCR evidence for historical-identity recovery.
    if result.get('ocr_reused') is True and hero.get('confident') is not True and hasattr(ocr,'recognize_fresh'):
        result=recognize_titles(ocr.recognize_fresh)
    result['hero_observation']=hero
    complete('total',started)
    return result
