"""Pure, fail-closed evidence for displaying a subset of three card titles.

This is only the existing three-column OCR geometry heuristic, not a game,
foreground, occlusion, or hero detector. Callers must retain those guards. Feed
ALL raw OCR rows from the current crop: dictionary-filtered candidates cannot
prove that an unknown third title is present. No pixels or ratings are retained.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import unicodedata


EMPTY_SLOTS = ('', '', '')
MAX_AGE = 4.0
MIN_TITLE_CONFIDENCE = .93


def _number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _literal(text):
    return ''.join(unicodedata.normalize('NFKC', text).split())


@dataclass(frozen=True)
class TitleSlot:
    slot: int
    text: str
    name: str
    confidence: float
    box: tuple


@dataclass(frozen=True)
class TitleEvidence:
    slots: tuple[TitleSlot, ...] = ()
    reason: str = 'Three explicit title rows are required'

    @property
    def valid(self):
        return len(self.slots) == 3


def title_evidence(ocr_lines, image_size, vocabulary, *, crop_top, frame_height):
    """Keep exactly one explicit, aligned title-shaped OCR row per column.

    Coordinates are crop-local; the title band is the existing .32-.55 of the
    full captured frame. Title-size/column/alignment limits match the existing
    automatic gate. Extra plausible rows in that band are ambiguous and reject
    the whole layout; two known names never stand in for a third title box.

    OCR confidence describes the text, not presence of the detection box. A
    finite score below .93 can therefore establish a title-shaped row, but can
    never produce a display name. Unknown text likewise remains an empty slot.
    """
    invalid = TitleEvidence
    if not isinstance(image_size, dict):
        return invalid(reason='Invalid crop size')
    width, height = image_size.get('width'), image_size.get('height')
    if not all(_number(x) and x >= 64 for x in (width, height, frame_height)):
        return invalid(reason='Invalid frame or crop size')
    if not _number(crop_top) or crop_top < 0 or crop_top + height > frame_height:
        return invalid(reason='Crop is outside the captured frame')
    if not isinstance(ocr_lines, (list, tuple)) or len(ocr_lines) > 400:
        return invalid(reason='Raw OCR rows are missing or incomplete')
    if isinstance(vocabulary, (str, bytes)):
        return invalid(reason='Invalid vocabulary')
    try:
        names = set(name for name in vocabulary if isinstance(name, str) and name)
    except TypeError:
        return invalid(reason='Invalid vocabulary')
    exact = {}
    for name in names:
        exact.setdefault(_literal(name), []).append(name)
    rows = []
    for row in ocr_lines:
        # Malformed rows might conceal an extra title and cannot be discarded
        # as harmless without valid geometry locating them outside the band.
        if not isinstance(row, dict):
            return invalid(reason='Malformed OCR row')
        box = row.get('box')
        if (not isinstance(box, (list, tuple)) or len(box) != 4
                or any(not isinstance(point, (list, tuple)) or len(point) != 2
                       or any(not _number(v) for v in point) for point in box)):
            return invalid(reason='Invalid OCR box')
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
        if left < 0 or right > width or top < 0 or bottom > height:
            return invalid(reason='OCR box is outside the crop')
        area = abs(sum(box[i][0] * box[(i + 1) % 4][1]
                       - box[(i + 1) % 4][0] * box[i][1] for i in range(4))) / 2
        if area <= 0:
            return invalid(reason='OCR box has no enclosed area')
        x, y = (left + right) / 2 / width, (top + bottom) / 2 / height
        full_y = crop_top + (top + bottom) / 2
        if not .32 * frame_height <= full_y <= .55 * frame_height:
            continue
        text, confidence = row.get('text'), row.get('confidence')
        if (not isinstance(text, str) or not _literal(text)
                or not _number(confidence) or not 0 <= confidence <= 1):
            return invalid(reason='Invalid title text or confidence')
        # Symbol-only decoration is not a textual title (the normal OCR name
        # matcher excludes it too). It cannot supply a missing third title.
        if not any(character.isalnum() for character in _literal(text)):
            continue
        if not (.015 <= (bottom - top) / height <= .20
                and .02 <= (right - left) / width <= .28
                and .08 <= y <= .82):
            # A row in the title band with unexpected geometry is not evidence
            # that an arbitrary second row in the same column is the title.
            return invalid(reason='Unexpected OCR row in the title band')
        matches = exact.get(_literal(text), ())
        name = matches[0] if len(matches) == 1 and confidence >= MIN_TITLE_CONFIDENCE else ''
        rows.append((x, y, text, name, float(confidence), tuple(tuple(p) for p in box)))
    if len(rows) != 3:
        return invalid(reason='Exactly three explicit title rows are required')
    rows.sort(key=lambda row: row[0])
    if not all(i / 3 + .02 <= row[0] <= (i + 1) / 3 - .02
               for i, row in enumerate(rows)):
        return invalid(reason='One title in each of three columns is required')
    if max(row[1] for row in rows) - min(row[1] for row in rows) > .06:
        return invalid(reason='Title rows are not aligned')
    if len({_literal(row[2]) for row in rows}) != 3:
        return invalid(reason='Repeated titles are ambiguous')
    slots = tuple(TitleSlot(i + 1, row[2], row[3], row[4], row[5])
                  for i, row in enumerate(rows))
    return TitleEvidence(slots, 'Three explicit title rows with safe per-slot names')


@dataclass
class PartialCandidateState:
    """Two independent fresh OCR frames per slot, with no old-name fallback.

    ``context`` must bind target identity, ROI, data version, confirmed hero,
    and scene lifecycle. It must stay equal across consecutive safe captures.
    On focus/occlusion/hero/target/Stop/manual-edit invalidation, call clear().
    ``guards_passed`` must describe the caller's current full safety checks.

    A cache hit may only sustain already confirmed matching names when the
    caller has verified identical current crop pixels and current scene/HUD.
    It never increments independent OCR evidence. Always display visible(now)
    or observe()'s returned tuple, never private retained continuity state.
    """
    _context: object = field(default=None, init=False, repr=False)
    _last_serial: int = field(default=-1, init=False, repr=False)
    _last_capture: float | None = field(default=None, init=False, repr=False)
    _last_ocr: float | None = field(default=None, init=False, repr=False)
    _candidates: tuple = field(default=EMPTY_SLOTS, init=False, repr=False)
    _counts: tuple = field(default=(0, 0, 0), init=False, repr=False)
    _offered: tuple = field(default=EMPTY_SLOTS, init=False, repr=False)

    def clear(self):
        """Revoke all display and continuity evidence; keep replay watermark."""
        self._last_capture = self._last_ocr = None
        self._candidates = self._offered = EMPTY_SLOTS
        self._counts = (0, 0, 0)

    def visible(self, now, *, guards_passed=True):
        if guards_passed is not True:
            self.clear()
            return EMPTY_SLOTS
        if (not _number(now) or self._last_capture is None
                or not 0 <= now - self._last_capture <= MAX_AGE):
            return EMPTY_SLOTS
        return self._offered

    def observe(self, evidence, *, frame_serial, captured_at, now, context,
                guards_passed, ocr_reused):
        """Apply one result; unsafe/unknown/changed slots disappear immediately.

        A strictly increasing capture serial AND capture timestamp identify
        new frames. False for ``ocr_reused`` must mean OCR really ran on this
        frame. None/missing provenance is never interpreted as a fresh OCR.
        """
        if (guards_passed is not True or context is None
                or not isinstance(evidence, TitleEvidence) or not evidence.valid
                or not isinstance(frame_serial, int) or isinstance(frame_serial, bool)
                or frame_serial < 0 or not _number(captured_at) or captured_at < 0
                or not _number(now) or not 0 <= now - captured_at <= MAX_AGE
                or type(ocr_reused) is not bool):
            self.clear()
            return EMPTY_SLOTS
        if frame_serial <= self._last_serial:
            self.clear()
            return EMPTY_SLOTS
        self._last_serial = frame_serial
        if context != self._context:
            self.clear()
            self._context = context
        if self._last_capture is not None and captured_at <= self._last_capture:
            self.clear()
            return EMPTY_SLOTS
        # A UI TTL expiry may hide cards while a still-fresh result is in
        # flight. Measure consecutive evidence by capture times, not delivery
        # times, without extending the four-second visible-result budget.
        if self._last_ocr is not None and captured_at - self._last_ocr > MAX_AGE:
            self.clear()
        current = tuple(slot.name for slot in evidence.slots)
        if ocr_reused:
            self._counts = tuple(count if name and name == prior else 0
                                 for name, prior, count in zip(current, self._candidates, self._counts))
            # The cache cannot seed a new first observation either.
            self._candidates = tuple(name if count else ''
                                     for name, count in zip(current, self._counts))
        else:
            self._counts = tuple(min(count + 1, 2) if name and name == prior
                                 else 1 if name else 0
                                 for name, prior, count in zip(current, self._candidates, self._counts))
            self._candidates = current
            self._last_ocr = captured_at
        self._offered = tuple(name if count >= 2 else ''
                              for name, count in zip(current, self._counts))
        self._last_capture = captured_at
        return self.visible(now, guards_passed=guards_passed)
