"""Conservative pixel-only card borders, independent of OCR title identity.

A title box is an anchor, never a card boundary. All three closed rectangular
outlines must be visible and unambiguous. No screen-thirds or historical-position
fallback is used. This is a geometric check, NOT proof of game/foreground or
absence of an interior occluder; callers retain their scene/occlusion guards.
Only Pillow and NumPy (already used by local vision) are needed. Unsupported
artwork deliberately returns None rather than placing badges over title text.
"""
from dataclasses import dataclass, replace
import hashlib
import io
import math


@dataclass(frozen=True)
class CardGeometry:
    rects: tuple
    size: tuple
    frame_digest: str
    anchors: tuple
    space: str = 'crop'

    def matches(self, image_bytes, *, _decoded_rgb=None):
        """Verify fresh borders; optional decode must belong to this exact call.

        _decoded_rgb is internal-only and must be the RGB decode of these exact
        immutable bytes, never a cached image. Header equality checks dimensions,
        not pixel identity; same-call ownership remains the caller invariant.
        """
        try:
            if _decoded_rgb is None:
                image = _image(image_bytes)
            else:
                from PIL import Image
                with Image.open(io.BytesIO(image_bytes)) as header:
                    if (_decoded_rgb.mode != 'RGB' or _decoded_rgb.size != header.size
                            or header.width * header.height > 16_000_000):
                        return False
                image = _decoded_rgb
            return _verify_edges(image, self)
        except (ImportError, OSError, ValueError, TypeError, IndexError, AttributeError):
            return False


def _image(data):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as source:
        if source.width * source.height > 16_000_000:
            raise ValueError('Frame exceeds local geometry limit')
        source.load()
        return source.convert('RGB')


def _anchors(candidates, width, height):
    if not isinstance(candidates, (tuple, list)) or len(candidates) != 3:
        raise ValueError('Three observed title boxes required')
    boxes, extents = [], []
    for candidate in candidates:
        box = candidate.get('box') if isinstance(candidate, dict) else candidate.box
        if len(box) != 4:
            raise ValueError('Four title corners required')
        points = tuple(tuple(p) for p in box)
        if any(len(p) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                 or not math.isfinite(v) for v in p) for p in points):
            raise ValueError('Invalid title coordinates')
        xs, ys = zip(*points)
        extent = (min(xs), min(ys), max(xs), max(ys))
        l, t, r, b = extent
        if not (0 <= l < r < width and 0 <= t < b < height and b-t >= 4):
            raise ValueError('Title is outside frame')
        boxes.append(points)
        extents.append(extent)
    if any(extents[i][2] >= extents[i+1][0] for i in range(2)):
        raise ValueError('Title slots must be distinct and ordered')
    return tuple(boxes), extents


def _groups(indices, gap):
    groups = []
    for value in indices:
        value = int(value)
        if not groups or value - groups[-1][-1] > gap:
            groups.append([value])
        else:
            groups[-1].append(value)
    return groups


def _continuous(values):
    """Require nearly complete edges, rejecting long missing/occluded sections."""
    import numpy as np
    if len(values) < 8 or float(np.mean(values)) < .90:
        return False
    missing = np.flatnonzero(~values)
    return not missing.size or max(map(len, _groups(missing, 1))) <= max(2, len(values)*.035)


def _detect_card_geometry(image, crop_bytes, candidates, image_size):
    """Return three crop-normalized (x,y,width,height) rectangles or None.

    Accept dict candidates or TitleSlot objects, including unknown names: text
    recognition and geometry are separate. Border contrast and continuity are
    checked from THIS image. Rounded corners and narrow double outlines are
    allowed; ambiguous nested outlines and cropped borders are rejected.
    """
    try:
        import numpy as np
        w, h = image.size
        if image_size != {'width': w, 'height': h} or min(w, h) < 64:
            return None
        anchors, titles = _anchors(candidates, w, h)
        pixels = np.asarray(image, dtype=np.int16)
        # Color contrast catches colored borders even at equal luminance.
        gx = np.zeros((h, w), dtype=bool)
        gy = np.zeros((h, w), dtype=bool)
        span = max(2, round(min(t[3]-t[1] for t in titles)*.06))
        gx[:, span:] = np.max(np.abs(pixels[:, span:] - pixels[:, :-span]), axis=2) >= 22
        gy[span:, :] = np.max(np.abs(pixels[span:, :] - pixels[:-span, :]), axis=2) >= 22
        result = []
        for slot, (tl, tt, tr, tb) in enumerate(titles):
            th = tb-tt
            xmin = 1 if slot == 0 else math.ceil((titles[slot-1][2]+tl)/2)
            xmax = w-2 if slot == 2 else math.floor((tr+titles[slot+1][0])/2)
            band0, band1 = max(1, int(tt-th)), min(h-1, math.ceil(tb+th))
            vertical = np.flatnonzero(np.mean(gx[band0:band1], axis=0) >= .90)
            gap = max(2, round(th*.13))
            lefts = _groups([x for x in vertical if xmin <= x < tl-th*.15], gap)
            rights = _groups([x for x in vertical if tr+th*.15 < x <= xmax], gap)
            possibilities = []
            for left in lefts:
                for right in rights:
                    l, r = left[0]-1, right[-1]
                    cw = r-l
                    if not max(tr-tl+th, th*4) <= cw <= w*.48:
                        continue
                    inset = max(3, math.ceil(cw*.06))
                    rows = np.flatnonzero(np.mean(gy[:, l+inset:r-inset], axis=1) >= .90)
                    tops = _groups([y for y in rows if max(1, tb-cw/0.35) < y < tt-th], gap)
                    bottoms = _groups([y for y in rows if tb+th < y < min(h-1, tt+cw/0.35)], gap)
                    for top in tops:
                        for bottom in bottoms:
                            t, b = top[0]-1, bottom[-1]
                            ch = b-t
                            if not .35 <= cw/ch <= 1.25:
                                continue
                            iy = max(3, math.ceil(ch*.045))
                            # Small neighborhoods allow antialiasing and outlines.
                            blur = max(1, round(th*.06))
                            ledge = np.any(gx[t+iy:b-iy, max(0,left[0]-blur):left[-1]+1+blur], axis=1)
                            redge = np.any(gx[t+iy:b-iy, max(0,right[0]-blur):right[-1]+1+blur], axis=1)
                            tedge = np.any(gy[max(0,top[0]-blur):top[-1]+1+blur, l+inset:r-inset], axis=0)
                            bedge = np.any(gy[max(0,bottom[0]-blur):bottom[-1]+1+blur, l+inset:r-inset], axis=0)
                            if all(_continuous(edge) for edge in (ledge, redge, tedge, bedge)):
                                possibilities.append((l, t, r, b))
            if not possibilities:
                return None
            # A thick ornamental frame has several parallel closed outlines.
            # Collapse only a narrow edge bundle, never unrelated nested panels.
            # The measured OUTERMOST boundary is the safe badge anchor.
            outer = (min(v[0] for v in possibilities), min(v[1] for v in possibilities),
                     max(v[2] for v in possibilities), max(v[3] for v in possibilities))
            ow, oh = outer[2]-outer[0], outer[3]-outer[1]
            if any(abs(v[i]-outer[i]) > (ow*.075 if i in (0,2) else oh*.055)
                   for v in possibilities for i in range(4)):
                return None
            # Envelope must itself be a tested closed outline, not assembled
            # from incompatible edges belonging to different panels.
            if outer not in possibilities:
                # Subpixel resampling can shift the strongest border pixel by
                # one or two pixels across its length. Still choose one fully
                # tested outline, never an untested combined rectangle.
                nearest = min(possibilities, key=lambda v: sum(abs(v[i]-outer[i]) for i in range(4)))
                if any(abs(nearest[i]-outer[i]) > span for i in range(4)):
                    return None
                outer = nearest
            result.append(outer)
        # A torn outer frame must not silently become its intact inner ornament.
        # Look for substantial parallel edge remnants just OUTSIDE every chosen
        # rectangle, bounded by neighboring cards so their borders cannot count.
        for slot,(l,t,r,b) in enumerate(result):
            reach=math.ceil((r-l)*.12);guard=span*3+2
            lo=max(1,l-reach, (result[slot-1][2]+l)//2 if slot else 1)
            hi=min(w-1,r+reach, (r+result[slot+1][0])//2 if slot<2 else w-1)
            iy=max(3,math.ceil((b-t)*.045))
            for start,end in ((lo,l-guard),(r+guard,hi)):
                if end>start:
                    remnants=gx[t+iy:b-iy,start:end]
                    for col in np.flatnonzero(np.mean(remnants,axis=0)>=.12):
                        runs=_groups(np.flatnonzero(remnants[:,col]),1)
                        if runs and max(map(len,runs))>=len(remnants)*.10:
                            return None
        widths = [r-l for l,t,r,b in result]
        heights = [b-t for l,t,r,b in result]
        if (max(widths)/min(widths) > 1.05 or max(heights)/min(heights) > 1.05
                or max(r[1] for r in result)-min(r[1] for r in result) > min(heights)*.02
                or any(result[i][2] >= result[i+1][0] for i in range(2))):
            return None
        rects = tuple((l/w, t/h, (r-l)/w, (b-t)/h) for l,t,r,b in result)
        return CardGeometry(rects, (w,h), hashlib.sha256(crop_bytes).hexdigest(), anchors)
    except (ImportError, OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError):
        return None


def detect_card_geometry(crop_bytes, candidates, image_size):
    """Decode this crop and measure all three actual closed card outlines."""
    try:
        return _detect_card_geometry(_image(crop_bytes), crop_bytes, candidates, image_size)
    except (OSError, ValueError, TypeError):
        return None


def detect_frame_card_geometry(image_bytes, candidates, image_size, roi):
    """Use full captured frame edges with crop-local accepted title anchors.

    image_size is the actual OCR crop size. Normalized output is FULL CLIENT,
    explicitly marked space='frame'. No OCR rerun, default ROI change, game
    memory, new capture, or old-frame geometry is involved.
    """
    try:
        from screen_capture import bounded_roi
        image = _image(image_bytes)
        left, top, width, height = bounded_roi(*image.size, roi)
        if image_size != {'width': width, 'height': height}:
            return None
        anchors, _ = _anchors(candidates, width, height)
        translated = [{'box': [(x+left, y+top) for x,y in box]} for box in anchors]
        found = _detect_card_geometry(image, image_bytes, translated,
                                     {'width': image.width, 'height': image.height})
        return replace(found, space='frame') if found else None
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _verify_edges(image, geometry):
    """Fresh bounded pixel strips; old rectangles alone never authorize reuse.

    Up to span+2 physical pixels accommodate antialiasing, smaller than the
    renderer's badge-to-card gap. Missing or broken edges fail closed.
    """
    import numpy as np
    if image.size != geometry.size or len(geometry.rects) != 3:
        return False
    w,h=image.size
    _,titles=_anchors([{'box':b} for b in geometry.anchors],w,h)
    span=max(2,round(min(t[3]-t[1] for t in titles)*.06))
    radius=span+2
    for x,y,rw,rh in geometry.rects:
        l,t,r,b=(round(x*w),round(y*h),round((x+rw)*w),round((y+rh)*h))
        if not (radius<l<r<w-radius and radius<t<b<h-radius):
            return False
        ix=max(3,math.ceil((r-l)*.06));iy=max(3,math.ceil((b-t)*.045))
        for axis,at,start,end in ((0,l,t+iy,b-iy),(0,r,t+iy,b-iy),
                                  (1,t,l+ix,r-ix),(1,b,l+ix,r-ix)):
            box=(at-radius,start,at+radius+1,end) if axis==0 else (start,at-radius,end,at+radius+1)
            pixels=np.asarray(image.crop(box),dtype=np.int16)
            if axis==0:
                edge=np.any(np.max(np.abs(pixels[:,span:]-pixels[:,:-span]),axis=2)>=22,axis=1)
            else:
                edge=np.any(np.max(np.abs(pixels[span:]-pixels[:-span]),axis=2)>=22,axis=0)
            if not _continuous(edge):
                return False
    return True


def refresh_frame_card_geometry(image_bytes, previous, candidates, image_size, roi, *, _decoded_rgb=None):
    """Reprove an already measured same-scope layout, else fully detect anew.

    Caller must scope previous to its current capture target, ROI and scene.
    _decoded_rgb is internal-only: the caller must pass the RGB decode of these
    exact immutable image_bytes, never a cached image. Header dimensions are
    checked without decoding pixels again.
    The output digest always belongs to image_bytes, including fast-path reuse.
    All twelve edges are measured again from fresh pixels; current title boxes
    must remain inside the corresponding cards. No identity/TTL authorization
    is granted here. Non-matching geometry falls back to full-frame detection.
    """
    try:
        from screen_capture import bounded_roi
        if _decoded_rgb is None:
            image=_image(image_bytes)
        else:
            from PIL import Image
            with Image.open(io.BytesIO(image_bytes)) as header:
                if (_decoded_rgb.mode!='RGB' or _decoded_rgb.size!=header.size
                        or header.width*header.height>16_000_000):
                    return None
            image=_decoded_rgb
        left,top,width,height=bounded_roi(*image.size,roi)
        if image_size!={'width':width,'height':height}:
            return None
        anchors,_=_anchors(candidates,width,height)
        translated=tuple(tuple((x+left,y+top) for x,y in b) for b in anchors)
        current=[{'box':b} for b in translated]
        if isinstance(previous,CardGeometry) and previous.space=='frame' and previous.size==image.size:
            contained=True
            for box,rect in zip(translated,previous.rects):
                l,t,rw,rh=rect;r=l+rw;b=t+rh
                if not all(l<x/image.width<r and t<y/image.height<b for x,y in box):
                    contained=False
            if contained and _verify_edges(image,previous):
                return replace(previous,anchors=translated,frame_digest=hashlib.sha256(image_bytes).hexdigest())
        found=_detect_card_geometry(image,image_bytes,current,{'width':image.width,'height':image.height})
        return replace(found,space='frame') if found else None
    except (ImportError,OSError,ValueError,TypeError,KeyError,AttributeError,IndexError,OverflowError):
        return None
