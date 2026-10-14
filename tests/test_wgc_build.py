"""Portable build/evidence contract tests, never a claim of Windows WGC execution."""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tests'))
from scripts import build_wgc_capture as build
import launcher
import windows_wgc_capture as smoke


def manifest():
    tool = {'signature_status':'Valid', 'signer_subject':'CN=Microsoft, O=Microsoft Corporation, C=US',
            'sha256':'e'*64, 'size':2048}
    return {'schema_version':1, 'protocol':1, 'filename':build.FILENAME, 'profile':build.PROFILE,
        'status':'passed', 'size':2048, 'sha256':'a'*64, 'source_sha256':'b'*64, 'build_recipe_sha256':'c'*64,
        'source_commit':'d'*40, 'sdk_version':build.SDK_VERSION, 'compile_flags':list(build.COMPILE_FLAGS),
        'link_flags':list(build.LINK_FLAGS), 'libraries':list(build.LIBRARIES), 'machine':'x64',
        'crt':'static-release-/MT', 'dependencies':['d3d11.dll','kernel32.dll'],
        'sdk_headers':{name:{'sha256':'e'*64,'size':2048} for name in build.SDK_HEADERS},
        'toolchain':{'product_id':build.microsoft_runtime.PRODUCT_ID,'compiler':dict(tool),'linker':dict(tool)}}


def passing_report(scale=1, frozen=True):
    proof=manifest()
    value={'schema_version':1, 'status':'passed', 'applicationVersion':smoke.__version__, 'frozen':frozen,
        'qt_platform':'windows', 'last_backend':'windows-graphics-capture', 'requested_app_scale':scale,
        'measured_qt_scale':scale, 'mean_channel_error':0., 'routed_mean_channel_error':0.,
        'helper':{'manifest':proof,'sha256':proof['sha256'],'size':proof['size']},
        'client_rect':{'x':20,'y':20,'width':round(320*scale),'height':round(240*scale)},
        'roi':[round(80*scale),round(60*scale),round(160*scale),round(120*scale)],
        'helper_process_count':12, 'negative_results':{}}
    value.update(dict.fromkeys(smoke.CHECK_FIELDS,True))
    for field,status in (('timeout_watchdog_passed','timeout'),('cancel_during_wait_passed','cancelled'),
                        ('cancel_before_launch_passed','cancelled'),('protected_window_passed','protected')):
        value['negative_results'][field]={'status':status,'elapsed_ms':200}
    return value


class WgcBuildTests(unittest.TestCase):
    def test_pinned_build_contract(self):
        build.validate_manifest(manifest())
        self.assertIn('/MT',build.COMPILE_FLAGS)
        self.assertNotIn('/MD',build.COMPILE_FLAGS)
        self.assertEqual(build.SDK_VERSION,'10.0.26100.0')
        self.assertEqual(build.LIBRARIES,('windowsapp.lib','d3d11.lib','dxgi.lib','dwmapi.lib','user32.lib'))
        source=(ROOT/'scripts/build_wgc_capture.py').read_text()
        self.assertNotIn('urlopen(',source)
        self.assertNotIn('pip install',source)

    def test_manifest_rejects_configuration_integrity_and_provenance_gaps(self):
        edits={'schema_version':True,'protocol':2,'filename':'other.exe','profile':'unreviewed',
            'status':'skipped','size':0,'sha256':'A'*64,'source_sha256':'no','build_recipe_sha256':None,
            'source_commit':'short','sdk_version':'latest','compile_flags':['/MD'], 'link_flags':[],
            'libraries':['unreviewed.lib'],'machine':'x86','crt':'dynamic','dependencies':['vcruntime140.dll'],
            'toolchain':{},'sdk_headers':{}}
        for key,value in edits.items():
            with self.subTest(key=key),self.assertRaises(RuntimeError):
                build.validate_manifest(dict(manifest(),**{key:value}))
        for edit in (lambda v:v['toolchain']['compiler'].update(signature_status='NotSigned'),
                     lambda v:v['toolchain']['linker'].update(sha256='x'),
                     lambda v:v['sdk_headers'][build.SDK_HEADERS[0]].update(size=0),
                     lambda v:v.update(error='even if status claims passed')):
            value=manifest();edit(value)
            with self.assertRaises(RuntimeError):build.validate_manifest(value)

    def test_dependencies_only_os_not_additional_installs(self):
        for name in ('d3d11.dll','dxgi.dll','dwmapi.dll','api-ms-win-core-winrt-l1-1-0.dll'):
            self.assertTrue(build.allowed_dependency(name))
        for name in ('opencv.dll','wgc.dll','vcruntime140.dll','msvcp140.dll','d3dcompiler_47.dll',None):
            self.assertFalse(build.allowed_dependency(name))

    def test_source_recipe_and_helper_bytes_are_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);folder=root/'build/native';folder.mkdir(parents=True)
            (root/'native').mkdir();(root/'scripts').mkdir()
            source=root/'native/wgc_capture.cpp';recipe=root/'scripts/build_wgc_capture.py'
            source.write_bytes(b'owned C++ fixture');recipe.write_bytes(b'owned Python fixture')
            helper=folder/build.FILENAME;helper.write_bytes(b'MZ'+b'x'*2046)
            value=manifest();value.update(build.record(helper))
            value.update(source_sha256=build.record(source)['sha256'],build_recipe_sha256=build.record(recipe)['sha256'])
            proof=folder/build.MANIFEST;proof.write_text(json.dumps(value))
            self.assertEqual(build.verify_built_helper(folder,root=root),value)
            for path in (source,recipe,helper):
                original=path.read_bytes();path.write_bytes(original+b'tampered')
                with self.subTest(path=path),self.assertRaises(RuntimeError):build.verify_built_helper(folder,root=root)
                path.write_bytes(original)

    def test_archive_requires_exact_native_bytes_and_manifest(self):
        value=manifest();binary=b'MZ'+b'x'*2046;value['sha256']=hashlib.sha256(binary).hexdigest()
        entries={'native/'+build.FILENAME:binary,'native/'+build.MANIFEST:json.dumps(value).encode()}
        class Archive:
            toc=entries
            def extract(self,name):return entries[name]
        self.assertEqual(build.verify_archive(Archive(),value),value)
        entries['native/'+build.FILENAME]=binary+b'x'
        with self.assertRaises(RuntimeError):build.verify_archive(Archive(),value)
        entries['native/'+build.FILENAME]=binary
        entries['native/'+build.MANIFEST]=json.dumps(dict(value,source_sha256='f'*64)).encode()
        with self.assertRaises(RuntimeError):build.verify_archive(Archive(),value)
        del entries['native/'+build.MANIFEST]
        with self.assertRaises(RuntimeError):build.verify_archive(Archive(),value)

    def test_package_cannot_silently_omit_helper(self):
        spec=(ROOT/'packaging/VGA-Aram-Helper.spec').read_text()
        self.assertIn('verify_built_helper()',spec)
        self.assertIn('WGC_FILENAME',spec);self.assertIn('WGC_MANIFEST',spec)
        self.assertIn("'wgc_capture'",spec);self.assertIn("'wgc_smoke'",spec)
        source=(ROOT/'scripts/build_windows.py').read_text()
        self.assertIn('verify_wgc_archive(archive, wgc_build)',source)
        self.assertIn("'native/vga-wgc-capture.exe'",source)

    def test_sdk_path_requires_existing_pinned_headers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            with self.assertRaises(RuntimeError):build.sdk_paths(root)
            for part in ('ucrt','shared','um','winrt','cppwinrt'):
                (root/'Include'/build.SDK_VERSION/part).mkdir(parents=True)
            for part in ('ucrt','um'):(root/'Lib'/build.SDK_VERSION/part/'x64').mkdir(parents=True)
            for name in build.SDK_HEADERS:
                path=root/'Include'/build.SDK_VERSION/name;path.parent.mkdir(exist_ok=True);path.write_bytes(b'header')
            includes,libraries,headers=build.sdk_paths(root)
            self.assertEqual(len(includes),5);self.assertEqual(len(libraries),2)
            self.assertEqual(set(headers),set(build.SDK_HEADERS))

    def test_windows_only_build_is_not_cross_compile_claim(self):
        with patch.object(build.sys,'platform','linux'),self.assertRaisesRegex(RuntimeError,'native Windows x64'):
            build.build()


class WgcAcceptanceContractTests(unittest.TestCase):
    def test_validates_all_scales_with_exact_helper_and_pixels(self):
        for scale in smoke.SCALES:
            for frozen in (True,False):
                value=passing_report(scale,frozen)
                smoke.validate_report(value,frozen=frozen,scale=scale,helper_build=manifest())

    def test_rejects_skips_fallbacks_offscreen_and_incomplete_checks(self):
        for key,new in [('status','unsupported'),('qt_platform','offscreen'),('last_backend','bounded-compositor'),
                        ('frozen',False),('mean_channel_error',20),('routed_mean_channel_error',float('nan')),
                        ('requested_app_scale',2),('helper_process_count',0),('roi',[0,0,320,240]),
                        ('helper',{}),('negative_results',{})]:
            value=passing_report();value[key]=new
            with self.subTest(key=key),self.assertRaises(RuntimeError):
                smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())
        for field in smoke.CHECK_FIELDS:
            value=passing_report();value[field]=False
            with self.subTest(field=field),self.assertRaises(RuntimeError):
                smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())

    def test_helper_input_is_not_a_user_chosen_target(self):
        module=types.ModuleType('wgc_smoke');module.run=lambda path: 0 if path==Path('wgc.json') else 1
        with patch.dict(sys.modules,{'wgc_smoke':module}):
            self.assertEqual(launcher.main(['--wgc-smoke-report','wgc.json']),0)
        for extra in (['--headless'],['--native-smoke-report','native.json'],['--self-test'],
                      ['--selection-smoke-input','input.json'],['--apply-update','plan.json'],
                      ['--update-health','health.json'],['--ready-file','ready.json'],['--licenses']):
            with self.subTest(extra=extra),self.assertRaises(SystemExit):
                launcher.main(['--wgc-smoke-report','wgc.json',*extra])

    def test_frozen_environment_is_no_python_compiler_or_foreign_qt(self):
        with tempfile.TemporaryDirectory() as temporary:
            result=smoke.child_environment({'SystemRoot':r'C:\Windows','PATH':r'C:\Python;C:\VC',
                'PYTHONPATH':'foreign','QT_PLUGIN_PATH':'foreign','QT_QPA_PLATFORM':'offscreen'},Path(temporary),1.5,frozen=True)
            self.assertEqual(result['PATH'],r'C:\Windows\System32;C:\Windows')
            self.assertNotIn('PYTHONPATH',result);self.assertNotIn('QT_PLUGIN_PATH',result)
            self.assertEqual(result['QT_QPA_PLATFORM'],'windows');self.assertEqual(result['QT_SCALE_FACTOR'],'1.5')

    def test_source_inventory_covers_native_python_recipe_and_bundle(self):
        self.assertEqual(len(set(smoke.SOURCE_FILES)),len(smoke.SOURCE_FILES))
        for name in smoke.SOURCE_FILES:self.assertTrue((ROOT/name).is_file(),name)
        for name in ('native/wgc_capture.cpp','wgc_capture.py','wgc_smoke.py','scripts/build_wgc_capture.py',
                     'packaging/VGA-Aram-Helper.spec','launcher.py'):
            self.assertIn(name,smoke.SOURCE_FILES)


if __name__=='__main__':unittest.main()
