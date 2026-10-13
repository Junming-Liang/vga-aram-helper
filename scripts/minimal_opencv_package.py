"""Bind official, experimental and adopted OpenCV profiles to exact evidence."""
from __future__ import annotations
import hashlib
from importlib import metadata
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import zipfile

from scripts.windows_package import (OFFICIAL_PROFILE, EXPERIMENT_PROFILE, CUSTOM_PROFILES,
                                    normalized_path, package_profile, validate_package_profile)
from scripts.build_minimal_opencv import validate_provenance

ROOT = Path(__file__).resolve().parents[1]
CUSTOM_VERSION = '5.0.0.93+vga1'
OFFICIAL_VERSION = '5.0.0.93'
EVIDENCE_NAMES = ('windows-opencv-build.json', 'windows-opencv-baseline.json',
                  'windows-opencv-candidate.json', 'windows-opencv-parity.json')


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def checked_proof(proof, *, profile=None):
    # The builder revalidates all pinned inputs, patch hashes, compiler/flags,
    # native PE imports and the exact complete license set at final verification.
    validate_provenance(proof)
    if proof.get('status') != 'passed' or proof.get('version') != CUSTOM_VERSION:
        raise RuntimeError('Custom OpenCV build provenance is missing or not passed')
    if proof.get('package_profile') not in CUSTOM_PROFILES or (profile is not None and proof['package_profile'] != profile):
        raise RuntimeError('Custom OpenCV provenance package profile mismatch')
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
    profile = package_profile()
    if profile == OFFICIAL_PROFILE:
        if version != OFFICIAL_VERSION:
            raise RuntimeError('Ordinary builds require the official pinned OpenCV wheel; custom builds require an explicit profile')
        return None
    if version != CUSTOM_VERSION:
        raise RuntimeError('Custom build requires truthful +vga1 OpenCV distribution metadata')
    path = proof_path or ROOT / 'build/minimal-opencv/provenance.json'
    return checked_proof(json.loads(Path(path).read_text(encoding='utf-8')), profile=profile)


def validate_build_profile(build):
    """Validate declared build identity without reading files or environment."""
    if not isinstance(build, dict):
        raise RuntimeError('Missing Windows build profile metadata')
    profile = validate_package_profile(build.get('package_profile'))
    if type(build.get('experimental')) is not bool or build['experimental'] != (profile == EXPERIMENT_PROFILE):
        raise RuntimeError('Windows package profile and experimental flag disagree')
    dependencies = build.get('dependencies')
    if not isinstance(dependencies, list) or any(not isinstance(row, dict) for row in dependencies):
        raise RuntimeError('Missing Windows dependency inventory')
    opencv = [row for row in dependencies
              if re.sub(r'[-_.]+', '-', str(row.get('name', '')).casefold()) == 'opencv-python-headless']
    expected_version = OFFICIAL_VERSION if profile == OFFICIAL_PROFILE else CUSTOM_VERSION
    if len(opencv) != 1 or opencv[0].get('version') != expected_version:
        raise RuntimeError('OpenCV dependency version does not match the package profile')
    proof = build.get('opencv_custom_build')
    if profile == OFFICIAL_PROFILE:
        if proof is not None:
            raise RuntimeError('Official OpenCV profile cannot carry custom provenance')
    elif (not isinstance(proof, dict) or proof.get('package_profile') != profile
          or proof.get('version') != CUSTOM_VERSION or proof.get('status') != 'passed'
          or not isinstance(build.get('source_commit'), str)
          or not re.fullmatch('[0-9a-f]{40}', build['source_commit'])
          or proof.get('source_commit') != build['source_commit']):
        raise RuntimeError('Custom OpenCV build/provenance package profile or source mismatch')
    return profile


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
        raise RuntimeError('Unused Pillow extensions returned in custom frozen EXE')


def verify_custom_notice_archive(path, proof):
    """Recheck every custom notice in the separately downloadable license ZIP."""
    proof = checked_proof(proof)
    expected = {'opencv-minimal/' + row['path']: row for row in proof['licenses']}
    provenance = 'opencv-minimal/BUILD-PROVENANCE.json'
    expected[provenance] = None
    directories = {parent.as_posix() + '/' for name in expected
                   for parent in PurePosixPath(name).parents if parent != PurePosixPath('.')}
    found, seen = set(), set()
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            name = item.filename
            normalized = normalized_path(name)
            if 'opencv-minimal' not in PurePosixPath(normalized).parts:
                continue
            if normalized in seen or stat.S_ISLNK(item.external_attr >> 16):
                raise RuntimeError('Duplicate or symbolic custom OpenCV notice ZIP member')
            seen.add(normalized)
            if item.is_dir():
                if name not in directories:
                    raise RuntimeError('Unexpected custom OpenCV notice ZIP directory: ' + name)
                continue
            if name not in expected:
                raise RuntimeError('Unexpected custom OpenCV notice ZIP member: ' + name)
            row = expected[name]
            if name == provenance:
                if item.file_size > 1_000_000 or json.loads(archive.read(item)) != proof:
                    raise RuntimeError('Custom OpenCV notice ZIP provenance differs')
            elif (item.file_size != row['size'] or digest_bytes(archive.read(item)) != row['sha256']):
                raise RuntimeError('Custom OpenCV notice ZIP bytes differ: ' + name)
            found.add(name)
    if found != set(expected):
        raise RuntimeError('Custom OpenCV notice ZIP is incomplete')


def verify_custom_source_archive(source_archive, reports, build):
    """Bind both parity processes and the custom recipe to released source bytes."""
    from model_inventory import EXPECTED_MODELS
    from scripts.probe_opencv_parity import SOURCE_FILES
    profile = validate_build_profile(build)
    if profile not in CUSTOM_PROFILES:
        raise RuntimeError('Custom OpenCV source evidence requires a custom package profile')
    proof = checked_proof(build['opencv_custom_build'], profile=profile)
    models = build.get('bundled_models')
    if (not isinstance(models, list) or len(models) != len(EXPECTED_MODELS)
            or any(not isinstance(row, dict) or set(row) != {'name', 'size', 'sha256'}
                   or not isinstance(row['name'], str) or type(row['size']) is not int or row['size'] <= 0
                   for row in models)
            or {row['name']: row['sha256'] for row in models} != EXPECTED_MODELS):
        raise RuntimeError('Custom OpenCV source evidence requires the pinned model inventory')
    comparisons = [json.loads((Path(reports) / ('windows-opencv-' + label + '.json')).read_text(encoding='utf-8'))
                   for label in ('baseline', 'candidate')]
    records = {'scripts/build_minimal_opencv.py': proof['recipe'],
               'packaging/opencv-minimal-patch.py': proof['patch']['script'],
               'packaging/opencv-build-requirements.txt': proof['build_requirements']}
    with zipfile.ZipFile(source_archive) as archive:
        for name in set(SOURCE_FILES) | set(records):
            matches = [item for item in archive.infolist() if item.filename == name]
            if (len(matches) != 1 or matches[0].is_dir() or matches[0].file_size > 1_000_000
                    or stat.S_ISLNK(matches[0].external_attr >> 16)):
                raise RuntimeError('Missing, duplicate or invalid custom OpenCV source ZIP member: ' + name)
            data = archive.read(matches[0])
            digest = digest_bytes(data)
            if name in records:
                row = records[name]
                if len(data) != row['size'] or digest != row['sha256']:
                    raise RuntimeError('Custom OpenCV source ZIP recipe bytes differ: ' + name)
            if name in SOURCE_FILES:
                for report in comparisons:
                    if not isinstance(report.get('inputs'), dict) or report['inputs'].get(name) != digest:
                        raise RuntimeError('OpenCV parity source differs from released source ZIP: ' + name)
    if any(report.get('models') != models for report in comparisons):
        raise RuntimeError('OpenCV parity models differ from the frozen build inventory')


def verify_custom_evidence(executable, reports, build):
    from PyInstaller.archive.readers import CArchiveReader
    from scripts.probe_opencv_parity import compare_reports
    profile = validate_build_profile(build)
    if profile not in CUSTOM_PROFILES:
        raise RuntimeError('Custom OpenCV evidence requires a custom package profile')
    reports = Path(reports)
    evidence = {name: json.loads((reports / name).read_text(encoding='utf-8')) for name in EVIDENCE_NAMES}
    proof = checked_proof(evidence['windows-opencv-build.json'], profile=profile)
    if (build.get('opencv_custom_build') != proof
            or proof.get('source_commit') != build.get('source_commit')):
        raise RuntimeError('Custom OpenCV build/provenance identity mismatch')
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


def verify_experiment_evidence(executable, reports, build):
    """Compatibility entry point, still limited to the isolated experiment."""
    if validate_build_profile(build) != EXPERIMENT_PROFILE:
        raise RuntimeError('Experimental evidence requires the experimental package profile')
    return verify_custom_evidence(executable, reports, build)
