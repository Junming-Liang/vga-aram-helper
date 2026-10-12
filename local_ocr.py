"""Optional local-only screenshot OCR plus conservative dictionary matching.

This module sends no image to a service and never clicks or selects in a game.
OCR confidence, name similarity and game win rate are distinct quantities.
"""
from __future__ import annotations
import argparse
from difflib import SequenceMatcher
import io
import json
import math
from pathlib import Path
import re
import threading
import unicodedata

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_LINES = 400


def normalized_name(text):
    text = unicodedata.normalize('NFKC', str(text))
    return ''.join(c for c in text.casefold() if c.isalnum())


def candidate_matches(lines, augment_names, min_ocr_confidence=0.55):
    """No invented names: returns dictionary matches, always for user review."""
    dictionary = [(name, normalized_name(name)) for name in augment_names if isinstance(name,str)]
    output = {}
    for line in lines[:MAX_LINES]:
        text = str(line.get('text',''))[:500]
        cleaned = normalized_name(text)
        confidence = line.get('confidence')
        if not isinstance(confidence,(int,float)) or isinstance(confidence,bool) or not math.isfinite(confidence) or not 0 <= confidence <= 1 or confidence < min_ocr_confidence or not cleaned:
            continue
        ranked = []
        for name, normalized in dictionary:
            if not normalized:
                continue
            if cleaned == normalized:
                similarity, method = 1.0, 'exact'
            elif len(normalized) >= 3 and normalized in cleaned and len(cleaned) <= len(normalized) + 8:
                similarity, method = 1.0, 'contained-name'
            else:
                similarity, method = SequenceMatcher(None,cleaned,normalized).ratio(), 'fuzzy-suggestion'
            ranked.append((similarity, name, method))
        ranked.sort(key=lambda row:(-row[0],row[1]))
        if not ranked or ranked[0][0] < 0.78:
            continue
        similarity,name,method=ranked[0]
        # Ambiguous fuzzy OCR remains unselected; never guess between near ties.
        if method == 'fuzzy-suggestion' and len(ranked)>1 and similarity-ranked[1][0]<0.1:
            continue
        current = {'name':name, 'recognized_text':text, 'ocr_confidence':round(float(confidence),4),
                   'name_similarity':round(similarity,4), 'match_method':method, 'box':line.get('box'),
                   'requires_confirmation':True}
        prior=output.get(name)
        if prior is None or (similarity,confidence)>(prior['name_similarity'],prior['ocr_confidence']):
            output[name]=current
    def left_to_right(item):
        box=item.get('box')
        return min((p[0] for p in box),default=10**9) if isinstance(box,list) else 10**9
    return sorted(output.values(),key=left_to_right)




class LocalOCR:
    def __init__(self):
        self._engine=None
        self._lock=threading.Lock()

    def recognize(self, image_bytes, augment_names):
        if not isinstance(image_bytes,bytes) or not image_bytes or len(image_bytes)>MAX_IMAGE_BYTES:
            raise ValueError('图片不能为空，且不能超过 8 MiB。')
        try:
            from PIL import Image, UnidentifiedImageError
            import numpy as np
            import onnxruntime
            onnxruntime.disable_telemetry_events()
            from rapidocr import RapidOCR
        except ImportError as exc:
            raise RuntimeError('未安装可选 OCR 依赖。请在虚拟环境安装 requirements-ocr.txt 后使用 --enable-ocr 启动。') from exc
        try:
            with Image.open(io.BytesIO(image_bytes)) as original:
                if original.format not in {'PNG','JPEG','WEBP','BMP'}:
                    raise ValueError('仅接受 PNG、JPEG、WebP 或 BMP 图片。')
                width,height=original.size
                if width*height>MAX_IMAGE_PIXELS or min(width,height)<16:
                    raise ValueError('图片尺寸需至少 16×16，且不超过 1600 万像素。')
                original.load()
                image=np.asarray(original.convert('RGB'))
        except (UnidentifiedImageError,OSError) as exc:
            raise ValueError('无法解码图片，请选择完整的普通截图文件。') from exc
        with self._lock:
            if self._engine is None:
                from model_inventory import verify_models
                import rapidocr
                model_dir=Path(rapidocr.__file__).resolve().parent/'models'
                verify_models(model_dir)
                self._engine=RapidOCR(params={**{'Det.model_path':str(model_dir/'PP-OCRv6_det_small.onnx'),'Rec.model_path':str(model_dir/'PP-OCRv6_rec_small.onnx'),'Cls.model_path':str(model_dir/'ch_ppocr_mobile_v2.0_cls_mobile.onnx')},**{'Global.use_cls':False,'Det.limit_type':'max','Det.limit_side_len':960,
                    'EngineConfig.onnxruntime.intra_op_num_threads':2,
                    'EngineConfig.onnxruntime.inter_op_num_threads':1}})
            # RapidOCR accepts ndarray. RGB input is converted to BGR expected by OpenCV pipeline.
            result=self._engine(image[:,:,::-1].copy())
        texts=getattr(result,'txts',None)
        scores=getattr(result,'scores',None)
        boxes=getattr(result,'boxes',None)
        lines=[]
        if texts is not None:
            for index,text in enumerate(texts[:MAX_LINES]):
                score=float(scores[index]) if scores is not None else 0.0
                box=boxes[index].tolist() if boxes is not None else None
                if not math.isfinite(score):score=0.0
                lines.append({'text':str(text)[:500],'confidence':score,'box':box})
        elapsed=getattr(result,'elapse_list',None)
        elapsed=[float(x) if x is not None and math.isfinite(float(x)) else None for x in elapsed] if elapsed is not None else []
        return {'mode':'local-screenshot-ocr','network_transmission':False,'image_saved':False,
                'image_size':{'width':width,'height':height},'ocr_lines':lines,
                'candidates':candidate_matches(lines,augment_names), 'elapsed_seconds':elapsed,
                'warning':'只识别用户选择的图片。候选需手动确认；OCR置信度与名称相似度均不是胜率。未验证真实游戏截图准确率。'}


def main():
    from engine import load_data
    parser=argparse.ArgumentParser(description='VGA乱斗助手：免费本地截图文字识别；不连接游戏或云端AI')
    parser.add_argument('image',type=Path)
    parser.add_argument('--data',type=Path,default=Path(__file__).parent/'fixtures/demo.json')
    args=parser.parse_args()
    try:
        if args.image.stat().st_size>MAX_IMAGE_BYTES:raise ValueError('图片超过 8 MiB。')
        result=LocalOCR().recognize(args.image.read_bytes(),load_data(args.data)['augments'])
    except (OSError,ValueError,RuntimeError) as exc:
        parser.exit(1,f'识别失败：{exc}\n')
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))


if __name__=='__main__':main()
