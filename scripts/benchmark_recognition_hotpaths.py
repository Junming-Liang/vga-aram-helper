"""Compare exact lossless transport and HUD search against a local git ref.

Owned procedural pixels by default. Optional caller-authorized public stills
are read-only inputs and never copied into the JSON report. This is a portable
microbenchmark, not Windows WGC, end-to-end latency or game-accuracy evidence.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def module_at(ref, filename, name):
    source = subprocess.run(['git', 'show', f'{ref}:{filename}'], cwd=ROOT,
                            check=True, capture_output=True).stdout
    module = types.ModuleType(name); sys.modules[name] = module
    exec(compile(source, f'{ref}/{filename}', 'exec'), module.__dict__)
    return module, hashlib.sha256(source).hexdigest()


def measured(fn, count):
    values = []
    for _ in range(count):
        started = time.perf_counter(); fn(); values.append((time.perf_counter()-started)*1000)
    return {'samples_ms': values, 'median_ms': statistics.median(values)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='6c0073dcf8dd112478b76b50941db6c1bc27422b')
    parser.add_argument('--runs', type=int, default=7)
    parser.add_argument('--image', type=Path, help='Optional authorized still, never exported')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 3 <= args.runs <= 30: parser.error('--runs must be 3..30')
    import numpy as np
    from PIL import Image
    from synthetic_vision import portraits, frame
    from hero_recognition import PortraitMatcher
    from screen_capture import encode_capture_png

    baseline, baseline_hash = module_at(args.baseline, 'hero_recognition.py', '_baseline_hero_benchmark')
    bank = portraits()
    for i in range(6, 173):
        pixels = np.random.default_rng(904+i).integers(20, 240, (8, 8, 3), dtype=np.uint8)
        bank[str(9001+i)] = Image.fromarray(pixels).resize((128, 128), Image.Resampling.BICUBIC)
    heroes = {f'Owned portrait {key}': {'championId': key} for key in bank}
    old = baseline.PortraitMatcher(bank, heroes); current = PortraitMatcher(bank, heroes)
    pixels = np.asarray(frame(bank['9001']))
    expected = old.recognize_array(pixels)
    assert expected['confident'] is True
    assert current.recognize_array(pixels) == expected
    def fresh(): assert old.recognize_array(pixels) == expected
    def reused(): assert current.recognize_array(pixels) == expected
    hud_old = measured(fresh, args.runs)
    hud_new = measured(reused, args.runs)
    # Changed complete search inputs must not accidentally share a cached score.
    altered = pixels.copy(); altered[619, 381, 0] ^= 1
    assert current.recognize_array(altered) == old.recognize_array(altered)
    assert current.recognize_array(pixels) == expected

    image = Image.open(args.image).convert('RGB') if args.image else frame(bank['9001'], width=3440, height=1440)
    def old_png():
        output = io.BytesIO(); image.save(output, format='PNG'); return output.getvalue()
    old_bytes = old_png(); new_bytes = encode_capture_png(image)
    with Image.open(io.BytesIO(new_bytes)) as decoded:
        assert decoded.size == image.size and decoded.tobytes() == image.tobytes()
    png_old = measured(old_png, args.runs)
    png_new = measured(lambda: encode_capture_png(image), args.runs)
    report = {
        'scope': 'Portable deterministic microbenchmark only; no Windows/game timing claim',
        'baseline_ref': args.baseline, 'baseline_hero_sha256': baseline_hash,
        'current_sha256': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                           for name in ('hero_recognition.py', 'screen_capture.py')},
        'platform': platform.system(), 'python': platform.python_version(),
        'hud': {'owned_template_count': len(bank), 'scales_per_template': 15,
                'complete_output_equal': True, 'fresh_all_template_search': hud_old,
                'exact_input_search_reuse_with_fresh_gates': hud_new},
        'png': {'input_kind': 'caller-authorized still' if args.image else 'owned procedural artwork',
                'size': list(image.size), 'decoded_pixels_equal': True,
                'default_level_6': dict(png_old, encoded_bytes=len(old_bytes)),
                'bounded_level_1': dict(png_new, encoded_bytes=len(new_bytes))}}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(text+'\n', encoding='utf8')
    print(text)


if __name__ == '__main__': main()
