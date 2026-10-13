"""Audited build-time patches to the exact OpenCV Python 5.0.0.93 sdist.

Only build frontend, wheel assembly, type stubs, and package identity are changed.
No C++ implementation or OCR model is modified. Hash mismatches fail closed.
"""
from __future__ import annotations
import hashlib
from pathlib import Path

FRONTEND_ADAPTER = r'''
import json as _vga_json
from skbuild.platform_specifics.abstract import CMakePlatform as _VGAPlatformBase, CMakeGenerator as _VGAGenerator

try:
    _vga_args = _vga_json.loads(os.environ["VGA_OPENCV_CMAKE_ARGS_JSON"])
except (KeyError, ValueError) as exc:
    raise RuntimeError("Missing or malformed reviewed OpenCV arguments") from exc
if (not isinstance(_vga_args, list) or not _vga_args
        or any(not isinstance(arg, str) or not re.fullmatch(r"-D[A-Za-z0-9_]+=[^\r\n\x00]+", arg) for arg in _vga_args)):
    raise RuntimeError("Invalid reviewed OpenCV CMake argument list")
_vga_options = dict(arg[2:].split("=", 1) for arg in _vga_args)
if len(_vga_options) != len(_vga_args):
    raise RuntimeError("Duplicate reviewed OpenCV CMake argument")
_vga_toolset = _vga_options.get("CMAKE_GENERATOR_TOOLSET", "")
if (not re.fullmatch(r"host=x64,version=14\.\d+\.\d+", _vga_toolset)
        or _vga_options.get("CMAKE_GENERATOR_PLATFORM") != "x64"
        or not all(_vga_options.get(key) for key in ("CMAKE_GENERATOR_INSTANCE", "CMAKE_C_COMPILER", "CMAKE_CXX_COMPILER", "CMAKE_LINKER"))):
    raise RuntimeError("Missing reviewed Community generator identity")

class _VGAPlatform(_VGAPlatformBase):
    def __init__(self):
        super().__init__()
        self.default_generators = [_VGAGenerator("Visual Studio 17 2022", toolset=_vga_toolset, arch="x64")]

    @property
    def generator_installation_help(self):
        return "The exact approved Community compiler must pass the generator test."

# Avoid WindowsPlatform's eager discovery of unrelated VS/Ninja environments.
cmaker.get_platform = _VGAPlatform

def setup(*args, **kwargs):
    kwargs["cmake_args"] = [*kwargs.get("cmake_args", ()), *_vga_args]
    return _vga_setup(*args, **kwargs)
'''

FILE_HASHES = {
    'cv2/version.py': ('34006b83568c39018d7151fdae827831f3fb6cff93e14b702fbf8190cd7187db', '68419d7f3b67f38fa7e46f9cc941179a2f74a41fe297983383574c0e297d2e00'),
    'setup.py': ('5b380b183fa3865b89efc30483ee640dc100d67512f6a066e7cb3f9e5eb989f6', 'b4e7548c049f2aba0e0d3b386bc92d50d8cf73361d1459eebb9b89b3ad78a2d4'),
    'opencv/modules/python/src2/typing_stubs_generation/api_refinement.py': ('4bc6e3b7616f6bf4fd84b5d7e8d5d6f0af03cf23db990e51af25b5e7004485fd', '92dd53237160d5ee562d651113970374d3da5de0eea70e331734b7c55bf9be18'),
    'opencv/modules/python/src2/typing_stubs_generation/generation.py': ('39419b707c9ffd9fae04be42eeab8572d1fad9c2bc2c3b1fa90d4f4559472bd1', '989c56d785b5c458855f0c32d0acb05f51af067820cf768e8fdb8f46379f2ec7'),
}


def transform(originals):
    """Verify all originals and all results before any caller writes a file."""
    if set(originals) != set(FILE_HASHES):
        raise RuntimeError('Unexpected OpenCV patch input set')
    updated = {}
    for name, raw in originals.items():
        if hashlib.sha256(raw).hexdigest() != FILE_HASHES[name][0]:
            raise RuntimeError('OpenCV patch preimage mismatch: ' + name)
        updated[name] = raw.decode('utf-8')

    def replace(name, old, new):
        if updated[name].count(old) != 1:
            raise RuntimeError('OpenCV patch must match exactly once: ' + name)
        updated[name] = updated[name].replace(old, new)

    replace('setup.py', 'from skbuild import cmaker, setup', 'from skbuild import cmaker, setup as _vga_setup\n'+FRONTEND_ADAPTER)
    replace('cv2/version.py','opencv_version = "5.0.0.93"','opencv_version = "5.0.0.93+vga1"')
    replace('setup.py','if os.name == "nt"\n            else []','if os.name == "nt" and "-DWITH_FFMPEG=OFF" not in os.environ.get("CMAKE_ARGS", "")\n            else []')
    replace('opencv/modules/python/src2/typing_stubs_generation/api_refinement.py','from .ast_utils import (find_function_node, SymbolName,','from .ast_utils import (find_function_node, SymbolName, ScopeNotFoundError, SymbolNotFoundError,')
    replace('opencv/modules/python/src2/typing_stubs_generation/api_refinement.py','    for symbol_name, refine_symbol in NODES_TO_REFINE.items():\n        refine_symbol(root, symbol_name)','    for symbol_name, refine_symbol in NODES_TO_REFINE.items():\n        # Minimal builds omit APIs outside the selected modules.\n        try:\n            find_function_node(root, symbol_name)\n        except (ScopeNotFoundError, SymbolNotFoundError):\n            continue\n        refine_symbol(root, symbol_name)')
    replace('opencv/modules/python/src2/typing_stubs_generation/generation.py','    for node in PREDEFINED_TYPES.values():\n        # if node does not have at least one required module skip it','    for node in PREDEFINED_TYPES.values():\n        # Feature2D aliases require the omitted features module.\n        if node.ctype_name in {"FeatureDetector", "DescriptorExtractor", "FeatureExtractor"} and "Feature2D" not in root.classes:\n            continue\n        # if node does not have at least one required module skip it')

    result = {name: value.encode('utf-8') for name, value in updated.items()}
    for name, raw in result.items():
        if hashlib.sha256(raw).hexdigest() != FILE_HASHES[name][1]:
            raise RuntimeError('OpenCV patch postimage mismatch: ' + name)
    return result


def apply(source):
    source = Path(source)
    if (source / '.git').exists():
        raise RuntimeError('Use the pinned sdist, without a root Git checkout')
    originals = {}
    for name in FILE_HASHES:
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError('Missing or linked OpenCV patch input: ' + name)
        originals[name] = path.read_bytes()
    result = transform(originals)
    for name, raw in result.items():
        (source / name).write_bytes(raw)
    return [{'path': name, 'before_sha256': pair[0], 'after_sha256': pair[1]}
            for name, pair in FILE_HASHES.items()]
