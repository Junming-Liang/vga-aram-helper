"""Sequential versus bounded parallel same-frame HUD plus actual OCR.

Reads only explicit already-permitted fixtures. No images are saved, copied or
downloaded. Requires trusted baseline Python source and existing local models.
This excludes Windows capture, GUI dispatch, and end-to-end live-game latency.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def summary(samples):
    return {'samples_ms': samples, 'median_ms': statistics.median(samples),
            'min_ms': min(samples), 'max_ms': max(samples)}


def semantic(result):
    # Compare every pre-existing semantic field. New partial-title evidence
    # has separate shape/temporal tests; measured OCR duration is not semantic.
    return {key: value for key, value in result.items() if key not in {'elapsed_seconds','partial_title_evidence'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'templates', 'fixtures', 'data', 'timing-image', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--samples', type=int, default=9)
    args = parser.parse_args()
    if not 7 <= args.samples <= 31:
        parser.error('--samples must be between 7 and 31')
    import cv2
    from PIL import Image
    from engine import normalize
    from hero_recognition import PortraitMatcher, recognize_frame
    from local_ocr import LocalOCR
    from synthetic_vision import encoded, frame, portraits
    paths = (args.baseline, ROOT/'hero_recognition.py', ROOT/'local_ocr.py')
    hashes = [digest(path.read_bytes()) for path in paths]
    spec = importlib.util.spec_from_file_location('portrait_phase_baseline', args.baseline)
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = baseline
    spec.loader.exec_module(baseline)
    roster_path = args.templates/'champion.en_US.json'
    roster = json.loads(roster_path.read_text())
    bank = {row['key']: Image.open(args.templates/'square'/row['image']['full']).convert('RGB')
            for row in roster['data'].values()}
    heroes = {row['name']: {'championId': row['key']} for row in roster['data'].values()}
    raw = json.loads(args.data.read_text())
    vocabulary = tuple(normalize(raw.get('data', raw))['augments'])
    real_matchers = (baseline.PortraitMatcher(bank, heroes), PortraitMatcher(bank, heroes))
    synthetic_bank = portraits()
    synthetic_heroes = {f'Original hero {i}': {'championId': str(9001+i)} for i in range(6)}
    synthetic_matchers = (baseline.PortraitMatcher(synthetic_bank, synthetic_heroes),
                          PortraitMatcher(synthetic_bank, synthetic_heroes))
    roi = (.15, .25, .7, .35)
    from frame_inference_worker import FrameInferenceWorker
    worker=FrameInferenceWorker()
    ocr = LocalOCR()
    ocr.recognize(encoded(Image.new('RGB', (896, 252), (26, 43, 67))), vocabulary)
    def run(payload, matcher, *, candidate):
        phases = {}
        started = time.perf_counter()
        def before_match(signature, crop):
            phases['before_match_ms'] = (time.perf_counter()-started)*1000
            phases['signature'] = signature
            phases['crop_sha256'] = digest(crop)
        def before_ocr(hero, crop):
            phases['before_ocr_ms'] = (time.perf_counter()-started)*1000
            if phases['crop_sha256'] != digest(crop):
                raise AssertionError('Phase crop changed')
        result = (recognize_frame(payload, roi, ocr, vocabulary, matcher,
                                  before_match=before_match, before_ocr=before_ocr, inference_worker=worker)
                  if candidate else baseline.recognize_frame(payload, roi, ocr, vocabulary, matcher))
        phases['total_ms'] = (time.perf_counter()-started)*1000
        return semantic(result), phases
    cases = []
    for row in json.loads(args.fixtures.read_text()):
        if row.get('path'):
            cases.append((row.get('image_url'), Path(row['path']).read_bytes(), real_matchers, 'public'))
    images = [(f'{w}x{h}', frame(synthetic_bank['9001'], width=w, height=h))
              for w, h in ((1280, 720), (1920, 1080), (2560, 1440), (3440, 1440))]
    images += [('sidebar', frame(synthetic_bank['9001'], side=True)),
               ('grayscale', frame(synthetic_bank['9001'], gray=True)),
               ('blank', Image.new('RGB', (1280, 720), (20, 30, 40))),
               ('portrait layout', frame(synthetic_bank['9001'], width=900, height=1200))]
    cases.extend((name, encoded(image), synthetic_matchers, 'synthetic') for name, image in images)
    records = []
    for name, payload, matchers, kind in cases:
        old, _ = run(payload, matchers[0], candidate=False)
        actual, phases = run(payload, matchers[1], candidate=True)
        if old != actual:
            raise AssertionError('Full pipeline output differs: '+str(name))
        records.append({'case': name, 'kind': kind, 'image_sha256': digest(payload),
                        'existing_output_parity_except_ocr_timing': True,
                        'result_sha256': digest(json.dumps(actual,ensure_ascii=False,sort_keys=True).encode('utf8')), 'hero_observation': actual.get('hero_observation'), 'candidate_phases': phases})
    payload = args.timing_image.read_bytes()
    for _ in range(2):
        for arm in (0, 1):
            run(payload, real_matchers[arm], candidate=bool(arm))
    timings = {'baseline_total': [], 'candidate_total': [], 'before_match': [], 'before_ocr': []}
    for iteration in range(args.samples):
        for arm in (iteration % 2, 1-iteration % 2):
            _, phases = run(payload, real_matchers[arm], candidate=bool(arm))
            timings['candidate_total' if arm else 'baseline_total'].append(phases['total_ms'])
            if arm:
                timings['before_match'].append(phases['before_match_ms'])
                timings['before_ocr'].append(phases['before_ocr_ms'])
    report = {
        'schema_version': 1, 'status': 'passed', 'applicationVersion': __import__('app_version').__version__,
        'driver_sha256': digest(Path(__file__).read_bytes()),
        'scope': 'Local sequential versus one reusable daemon parallel portrait+actual OCR pipeline parity and callback timings. Excludes Windows capture, GUI dispatch and live-game latency; no general accuracy claim or images copied.',
        'environment': {'platform': platform.platform(), 'python': platform.python_version(),
                        'opencv': cv2.__version__, 'threads': cv2.getNumThreads()},
        'baseline_sha256': hashes[0], 'candidate_sha256': hashes[1], 'local_ocr_sha256': hashes[2],
        'roster_sha256': digest(roster_path.read_bytes()), 'template_count': len(bank),
        'vocabulary_count': len(vocabulary), 'vocabulary_sha256': digest(json.dumps(vocabulary, ensure_ascii=False).encode()),
        'worker_sha256': digest((ROOT/'frame_inference_worker.py').read_bytes()),
        'roi': roi, 'cases': records, 'timing_image_sha256': digest(payload),
        'warmups_per_arm': 2, 'timing_ms': {name: summary(values) for name, values in timings.items()},
    }
    if [digest(path.read_bytes()) for path in paths] != hashes:
        raise RuntimeError('Implementation changed during validation; rerun')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'status': 'passed', 'public_cases': sum(row['kind']=='public' for row in records),
                      'synthetic_cases': sum(row['kind']=='synthetic' for row in records),
                      'timing_ms': report['timing_ms']}, indent=2))


if __name__ == '__main__':
    main()
