"""Compare an explicit local baseline with exact-template preparation.

Uses already permitted local portraits/screenshots. No download or image copy.
Timing is isolated portrait recognition on this host, never live capture/OCR
latency or general game-accuracy evidence. Baseline must be trusted local code.
"""
import argparse
import hashlib
import importlib.util
import json
import platform
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def timed(function):
    started = time.perf_counter()
    value = function()
    return value, (time.perf_counter()-started)*1000


def summary(samples):
    return {'samples_ms': samples, 'median_ms': statistics.median(samples),
            'min_ms': min(samples), 'max_ms': max(samples)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--templates', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--timing-image', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=9)
    args = parser.parse_args()
    if not 7 <= args.samples <= 31:
        parser.error('--samples must be between 7 and 31')
    import cv2
    import numpy as np
    from PIL import Image
    from hero_recognition import PortraitMatcher
    from synthetic_vision import encoded, frame, portraits
    source_paths = (args.baseline, ROOT/'hero_recognition.py')
    source_hashes = [digest(path.read_bytes()) for path in source_paths]
    spec = importlib.util.spec_from_file_location('portrait_benchmark_baseline', args.baseline)
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    constructors = (baseline.PortraitMatcher, PortraitMatcher)
    roster_path = args.templates/'champion.en_US.json'
    roster = json.loads(roster_path.read_text())
    bank = {row['key']: Image.open(args.templates/'square'/row['image']['full']).convert('RGB')
            for row in roster['data'].values()}
    heroes = {row['name']: {'championId': row['key']} for row in roster['data'].values()}
    matchers = [constructor(bank, heroes) for constructor in constructors]
    old, candidate = matchers
    for key, variants in candidate._scaled_templates.items():
        if [size for size, _ in variants] != list(range(20, 49, 2)):
            raise AssertionError('Template scale order changed')
        for size, pixels in variants:
            expected = cv2.resize(old.templates[key][1], (size, size), interpolation=cv2.INTER_AREA)
            np.testing.assert_array_equal(pixels, expected)
    cases = []
    for row in json.loads(args.fixtures.read_text()):
        if not row.get('path'):
            continue
        payload = Path(row['path']).read_bytes()
        observed = [matcher.recognize(payload) for matcher in matchers]
        if observed[0] != observed[1]:
            raise AssertionError('Public screenshot output differs: '+digest(payload))
        cases.append({'image_sha256': digest(payload), 'source_url': row.get('image_url'),
                      'observed': observed[1], 'exact_output_parity': True})
    synthetic_bank = portraits()
    synthetic_heroes = {f'Original hero {i}': {'championId': str(9001+i)} for i in range(6)}
    synthetic_matchers = [constructor(synthetic_bank, synthetic_heroes) for constructor in constructors]
    images = [(f'{w}x{h}', frame(synthetic_bank['9001'], width=w, height=h))
              for w, h in ((1280, 720), (1920, 1080), (2560, 1440), (3440, 1440))]
    images += [('sidebar', frame(synthetic_bank['9001'], side=True)),
               ('grayscale', frame(synthetic_bank['9001'], gray=True)),
               ('blank', Image.new('RGB', (1280, 720), (20, 30, 40))),
               ('portrait layout', frame(synthetic_bank['9001'], width=900, height=1200))]
    synthetic_cases = []
    for name, image in images:
        payload = encoded(image)
        observed = [matcher.recognize(payload) for matcher in synthetic_matchers]
        if observed[0] != observed[1]:
            raise AssertionError('Synthetic output differs: '+name)
        synthetic_cases.append({'case': name, 'observed': observed[1], 'exact_output_parity': True})
    payload = args.timing_image.read_bytes()
    for _ in range(2):
        for matcher in matchers:
            matcher.recognize(payload)
    timings, construction = [[], []], [[], []]
    for iteration in range(args.samples):
        for arm in (iteration % 2, 1-iteration % 2):
            _, elapsed = timed(lambda: matchers[arm].recognize(payload))
            timings[arm].append(elapsed)
    for iteration in range(args.samples):
        for arm in (iteration % 2, 1-iteration % 2):
            _, elapsed = timed(lambda: constructors[arm](bank, heroes))
            construction[arm].append(elapsed)
    report = {
        'schema_version': 1, 'status': 'passed',
        'scope': 'Exact local parity and isolated portrait timings; no live Windows capture, OCR, end-to-end latency or aggregate accuracy claim. No images copied.',
        'environment': {'platform': platform.platform(), 'python': platform.python_version(),
                        'opencv': cv2.__version__, 'threads': cv2.getNumThreads()},
        'baseline_sha256': source_hashes[0], 'candidate_sha256': source_hashes[1],
        'roster_sha256': digest(roster_path.read_bytes()), 'template_count': len(bank),
        'exact_resized_arrays': sum(len(variants) for variants in candidate._scaled_templates.values()),
        'cached_array_bytes': sum(pixels.nbytes for variants in candidate._scaled_templates.values()
                                  for _, pixels in variants),
        'public_cases': cases, 'synthetic_cases': synthetic_cases,
        'timing_image_sha256': digest(payload), 'warmups_per_arm': 2,
        'recognize': {'baseline': summary(timings[0]), 'candidate': summary(timings[1])},
        'initialization': {'baseline': summary(construction[0]), 'candidate': summary(construction[1])},
        'median_recognize_improvement_percent': 100*(1-statistics.median(timings[1])/statistics.median(timings[0])),
    }
    if [digest(path.read_bytes()) for path in source_paths] != source_hashes:
        raise RuntimeError('Source changed during benchmark; rerun')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({key: report[key] for key in ('status', 'template_count', 'cached_array_bytes',
          'recognize', 'initialization', 'median_recognize_improvement_percent')}, indent=2))


if __name__ == '__main__':
    main()
