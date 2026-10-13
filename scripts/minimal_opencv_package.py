"""Isolate the unapproved custom OpenCV experiment from ordinary publication."""
from __future__ import annotations
import hashlib
from importlib import metadata
import json
from pathlib import Path, PurePosixPath
import shutil

from scripts.windows_package import experimental_package, normalized_path
from scripts.build_minimal_opencv import validate_provenance

ROOT = Path(__file__).resolve().parents[1]
CUSTOM_VERSION = '5.0.0.93+vga1'
OFFICIAL_VERSION = '5.0.0.93'
EVIDENCE_NAMES = ('windows-opencv-build.json', 'windows-opencv-baseline.json',
                  'windows-opencv-candidate.json', 'windows-opencv-parity.json')


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def checked_proof(proof):
    # The builder revalidates all pinned inputs, patch hashes, compiler/flags,
    # native PE imports and the exact complete license set at final verification.
    validate_provenance(proof)
    if proof.get('status') != 'passed' or proof.get('version') != CUSTOM_VERSION:
        raise RuntimeError('Custom OpenCV build provenance is missing or not passed')
    native = proof.get('native', {})
    if type(native.get('size')) is not int or native['size'] <= 0 or len(native.get('sha256', '')) != 64:
        raise RuntimeError('Custom OpenCV native identity is missing')
    rows = proof.get('licenses')
    if not isinstance(rows, list) or not rows:
        raise RuntimeError('Complete custom OpenCV license inventory is required')
    seen = set()
    for row in rows:
        path = row.get('path', '')
        if (not path or '\\' in path or ':' in path or PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts
                or path in seen or type(row.get('size')) is not int or row['size'] <= 0
                or len(row.get('sha256', '')) != 64):
            raise RuntimeError('Invalid custom OpenCV license inventory')
        seen.add(path)
    return proof


def check_build_mode(version=None, proof_path=None):
    version = version or metadata.version('opencv-python-headless')
    if not experimental_package():
        if version != OFFICIAL_VERSION:
            raise RuntimeError('Ordinary builds require the official pinned OpenCV wheel; custom builds are experimental')
        return None
    if version != CUSTOM_VERSION:
        raise RuntimeError('Experimental build requires truthful +vga1 OpenCV distribution metadata')
    path = proof_path or ROOT / 'build/minimal-opencv/provenance.json'
    return checked_proof(json.loads(Path(path).read_text(encoding='utf-8')))


def copy_custom_licenses(destination):
    proof = check_build_mode()
    if not proof:
        return []
    source = ROOT / 'build/minimal-opencv/licenses'
    destination = Path(destination)
    found = []
    for row in proof['licenses']:
        path = source / row['path']
        if path.is_symlink() or not path.is_file():
            raise RuntimeError('Custom OpenCV notice is missing or symbolic')
        data = path.read_bytes()
        if len(data) != row['size'] or digest_bytes(data) != row['sha256']:
            raise RuntimeError('Custom OpenCV notice changed after build')
        target = destination / 'opencv-minimal' / row['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        found.append(target.relative_to(destination).as_posix())
    target = destination / 'opencv-minimal/BUILD-PROVENANCE.json'
    target.write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
    found.append(target.relative_to(destination).as_posix())
    return found


def verify_custom_archive(archive, proof):
    proof = checked_proof(proof)
    names = {normalized_path(name): name for name in archive.toc}
    if len(names) != len(archive.toc):
        raise RuntimeError('Ambiguous custom OpenCV archive names')
    native = [original for name, original in names.items() if name == 'cv2/cv2.pyd']
    if len(native) != 1:
        raise RuntimeError('Custom OpenCV native library missing from frozen EXE')
    raw = archive.extract(native[0])
    if len(raw) != proof['native']['size'] or digest_bytes(raw) != proof['native']['sha256']:
        raise RuntimeError('Frozen OpenCV native bytes differ from compiled candidate')
    metadata_names = [original for name, original in names.items()
                      if name.startswith('opencv_python_headless-') and name.endswith('.dist-info/metadata')]
    if len(metadata_names) != 1 or ('\nVersion: ' + CUSTOM_VERSION + '\n').encode() not in archive.extract(metadata_names[0]).replace(b'\r\n', b'\n'):
        raise RuntimeError('Frozen OpenCV metadata does not identify the custom wheel')
    for row in proof['licenses']:
        name = 'licenses/opencv-minimal/' + row['path'].lower()
        if name not in names:
            raise RuntimeError('Frozen custom OpenCV notice is missing: ' + row['path'])
        data = archive.extract(names[name])
        if len(data) != row['size'] or digest_bytes(data) != row['sha256']:
            raise RuntimeError('Frozen custom OpenCV notice differs: ' + row['path'])
    provenance = names.get('licenses/opencv-minimal/build-provenance.json')
    if not provenance or json.loads(archive.extract(provenance)) != proof:
        raise RuntimeError('Frozen custom OpenCV provenance differs')
    if any(name.startswith('pil/_imagingft.') or name.startswith('pil/_imagingcms.') for name in names):
        raise RuntimeError('Unused Pillow extensions returned in experimental frozen EXE')


def verify_experiment_evidence(executable, reports, build):
    from PyInstaller.archive.readers import CArchiveReader
    from scripts.probe_opencv_parity import compare_reports
    reports = Path(reports)
    evidence = {name: json.loads((reports / name).read_text(encoding='utf-8')) for name in EVIDENCE_NAMES}
    proof = checked_proof(evidence['windows-opencv-build.json'])
    if (build.get('experimental') is not True or build.get('opencv_custom_build') != proof
            or proof.get('source_commit') != build.get('source_commit')):
        raise RuntimeError('Experimental build/provenance identity mismatch')
    baseline, candidate = (evidence['windows-opencv-' + label + '.json'] for label in ('baseline', 'candidate'))
    compared = compare_reports(baseline, candidate)
    if compared != evidence['windows-opencv-parity.json'] or compared.get('status') != 'passed':
        raise RuntimeError('Custom OpenCV parity/performance proof did not pass')
    if candidate.get('native', {}).get('sha256') != proof['native']['sha256']:
        raise RuntimeError('OpenCV parity did not use the compiled native bytes')
    selftest = json.loads((reports / 'windows-exe-self-test.json').read_text(encoding='utf-8'))
    if selftest.get('ort_telemetry_opt_out') != '1':
        raise RuntimeError('Frozen OCR process did not retain its early telemetry opt-out')
    smoke = json.loads((reports / 'windows-exe-smoke.json').read_text(encoding='utf-8'))
    expected = ['星火共鸣（演示）', '晶盾回路（演示）', '风步微光（演示）']
    if smoke.get('icc_image_formats') != {kind: expected for kind in ('PNG', 'JPEG', 'WEBP')}:
        raise RuntimeError('ICC-bearing screenshots were not verified by the frozen EXE')
    verify_custom_archive(CArchiveReader(str(executable)), proof)
    return EVIDENCE_NAMES
