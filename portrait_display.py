"""Bounded display copies of the already verified public portrait bank.

No fetching, path lookup from champion names, or recognition is performed here.
Only exact canonical IDs may select an image. Source images remain untouched.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

from PySide6 import QtCore, QtGui


class PortraitDisplayBank:
    MAX_PORTRAITS = 400
    MAX_EDGE = 128

    def __init__(self):
        self._images = {}
        self.revision = 0

    def replace(self, portraits):
        """Copy at most 400 decoded images, each at most 128x128 RGB pixels."""
        from PIL import Image
        images = {}
        if isinstance(portraits, dict) and len(portraits) <= self.MAX_PORTRAITS:
            for champion_id, image in portraits.items():
                if not self.valid_id(champion_id) or not isinstance(image, Image.Image):
                    continue
                if image.width != image.height or not 64 <= image.width <= 512:
                    continue
                rgb = image.convert('RGB')
                if rgb.width > self.MAX_EDGE:
                    rgb = rgb.resize((self.MAX_EDGE, self.MAX_EDGE), Image.Resampling.LANCZOS)
                payload = rgb.tobytes()
                # Detach from both the transient bytes and caller-owned PIL image.
                images[champion_id] = QtGui.QImage(payload, rgb.width, rgb.height,
                    rgb.width * 3, QtGui.QImage.Format.Format_RGB888).copy()
        self._images = images
        self.revision += 1

    @staticmethod
    def valid_id(champion_id):
        return isinstance(champion_id, str) and re.fullmatch(r'[0-9]{1,10}', champion_id) is not None

    def hero_id(self, data, hero):
        heroes = data.get('heroes', {}) if isinstance(data, dict) else {}
        record = heroes.get(hero) if isinstance(heroes, dict) and isinstance(hero, str) else None
        champion_id = record.get('championId') if isinstance(record, dict) else None
        if not self.valid_id(champion_id):
            return None
        # An inconsistent local table cannot assign one portrait to two identities.
        if sum(isinstance(row, dict) and row.get('championId') == champion_id
               for row in heroes.values()) != 1:
            return None
        return champion_id

    def pixmap(self, champion_id, size, dpr=1.0):
        if not self.valid_id(champion_id) or champion_id not in self._images:
            return None
        if (not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= 256
                or not isinstance(dpr, (int, float)) or isinstance(dpr, bool)
                or not math.isfinite(dpr) or not 0.5 <= dpr <= 4):
            return None
        edge = max(1, round(size * dpr))
        pixmap = QtGui.QPixmap.fromImage(self._images[champion_id]).scaled(
            edge, edge, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation)
        pixmap.setDevicePixelRatio(dpr)
        return pixmap


def cached_roster_fingerprint(cache_dir):
    """Observe actual verified roster availability, without loading new assets."""
    try:
        cache = Path(cache_dir)
        with (cache / 'manifest.json').open('rb') as handle:
            manifest_bytes = handle.read(256 * 1024 + 1)
        if len(manifest_bytes) > 256 * 1024:
            return None
        manifest = json.loads(manifest_bytes)
        version = manifest['version']
        if not isinstance(version, str) or not re.fullmatch(r'\d{1,3}\.\d{1,3}\.\d{1,3}', version):
            return None
        with (cache / f'roster-{version}.json').open('rb') as handle:
            roster = handle.read(2 * 1024 * 1024 + 1)
        if len(roster) > 2 * 1024 * 1024:
            return None
        digest = hashlib.sha256(roster).hexdigest()
        return (version, digest) if digest == manifest.get('rosterSha256') else None
    except (OSError, ValueError, KeyError, TypeError):
        return None
