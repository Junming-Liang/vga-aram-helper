"""Fail closed unless the smaller exact EXE passed formats and native OTA checks."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.windows_package import assert_slim_inventory, measure_archive

FORMATS = {'PNG', 'JPEG', 'WEBP', 'BMP'}
NAMES = ['星火共鸣（演示）', '晶盾回路（演示）', '风步微光（演示）']


def validate_evidence(size, smoke, ota, source_commit):
    if size.get('status') != 'passed' or size.get('source_commit') != source_commit:
        raise RuntimeError('Size measurement failed or belongs to another source commit')
    identity = size['executable']
    if smoke.get('status') != 'passed' or smoke.get('executable_sha256') != identity['sha256']:
        raise RuntimeError('Frozen smoke test did not pass on the measured EXE')
    formats = smoke.get('supported_image_formats', {})
    if set(formats) != FORMATS or any(names != NAMES for names in formats.values()):
        raise RuntimeError('Frozen OCR coverage for all four supported image formats is required')
    if (ota.get('status') != 'passed' or ota.get('executable_sha256') != identity['sha256'] or
            ota.get('executable_bytes') != identity['size'] or ota.get('release_source_commit') != source_commit or
            ota.get('harness_source_commit') != source_commit or ota.get('all_owned_processes_exited') is not True):
        raise RuntimeError('Native OTA test did not pass on the exact measured source/EXE')
    cases = ota.get('cases', [])
    if len(cases) != 2 or {case.get('case') for case in cases} != {'success-concurrency', 'version-mismatch-rollback'}:
        raise RuntimeError('Both native OTA success/concurrency and rollback cases are required')
    for case in cases:
        if (case.get('status') != 'passed' or case.get('original_sha256') != identity['sha256'] or
                case.get('target_sha256') != identity['sha256'] or case.get('actual_file_identity_changed') is not True):
            raise RuntimeError('Native OTA case failed or used different bytes')


def main():
    from PyInstaller.archive.readers import CArchiveReader
    executable = ROOT / 'dist' / 'VGA-Aram-Helper.exe'
    reports = ROOT / 'reports'
    size = json.loads((reports / 'windows-package-size.json').read_text(encoding='utf-8'))
    archive = CArchiveReader(str(executable))
    assert_slim_inventory(archive.toc)
    measured = measure_archive(archive, executable)
    if any(size.get(key) != value for key, value in measured.items()):
        raise RuntimeError('Saved package-size evidence differs from remeasured EXE')
    validate_evidence(size,
        json.loads((reports / 'windows-exe-smoke.json').read_text(encoding='utf-8')),
        json.loads((reports / 'windows-ota-smoke.json').read_text(encoding='utf-8')),
        os.environ['GITHUB_SHA'])
    print(json.dumps({'status': 'passed', 'bytes': measured['executable']['size'],
                     'saved_percent': measured['saved_percent'], 'same_binary_ota': 'passed',
                     'supported_image_formats': sorted(FORMATS)}))


if __name__ == '__main__':
    main()
