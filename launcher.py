#!/usr/bin/env python3
"""Double-click Windows entry point; bundled runtime and local OCR models."""
from __future__ import annotations
import argparse
import json
import multiprocessing
import os
from ocr_privacy import disable_telemetry_before_import
disable_telemetry_before_import()
from pathlib import Path
import sys
import threading
import traceback
from urllib.request import ProxyHandler, build_opener
from app_version import __version__

ROOT = Path(__file__).resolve().parent
APP_NAME = "VGA乱斗助手"


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def bundled_self_test() -> dict:
    """Exercise bundled model loading and actual inference without network/data APIs."""
    import hashlib
    import importlib.metadata
    from local_ocr import LocalOCR
    from model_inventory import verify_models
    models = verify_models()
    names = ["珠光护手", "炼狱导管", "双刀流"]
    engine = LocalOCR()
    fixture = ROOT / "fixtures" / "ocr-synthetic.png"
    result = engine.recognize(fixture.read_bytes(), names)
    actual = [item["name"] for item in result["candidates"]]
    if actual != names:
        raise RuntimeError(f"Bundled OCR fixture mismatch: {actual!r}")
    blank = engine.recognize((ROOT / "fixtures" / "ocr-blank.png").read_bytes(), names)
    if blank["candidates"]:
        raise RuntimeError("Blank image produced candidates")
    return {"status": "passed", "applicationVersion": __version__, "frozen": bool(getattr(sys, "frozen", False)),
            "bundled_models": models, "recognized": actual, "blank_candidates": 0,
            "ort_telemetry_opt_out": os.environ.get("ORT_DISABLE_TELEMETRY"),
            "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
            "versions": {package: importlib.metadata.version(package) for package in ("rapidocr", "onnxruntime", "numpy", "Pillow")},
            "scope": "Original synthetic Chinese image only; not real-game accuracy or anti-cheat validation."}


def print_licenses() -> None:
    for path in sorted((ROOT / "licenses").rglob("*")):
        if path.is_file():
            print(f"\n===== {path.relative_to(ROOT / 'licenses')} =====\n")
            print(path.read_text(encoding="utf-8", errors="replace"))


def complete_startup_health(url, update_health=None):
    """An OTA health marker requires real bundled OCR and serving HTTP."""
    if update_health is not None:
        print("正在验证更新后的内置 OCR 模型及实际识别能力…", flush=True)
        result = bundled_self_test()
        if result.get("status") != "passed":
            raise RuntimeError("Updated application failed bundled OCR self-test")
    opener = build_opener(ProxyHandler({}))
    with opener.open(url + "/health", timeout=10) as response:
        health = json.load(response)
    if health.get("status") != "ok":
        raise RuntimeError("Local HTTP readiness check failed")
    if update_health is not None:
        from updates import mark_update_healthy
        mark_update_healthy(update_health)
    return health


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} {__version__}：双击即用的本地助手", allow_abbrev=False)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--version-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--licenses-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--wgc-smoke-report", type=Path, help=argparse.SUPPRESS)
    session_modes = parser.add_mutually_exclusive_group()
    session_modes.add_argument("--wgc-session-smoke-report", type=Path, help=argparse.SUPPRESS)
    session_modes.add_argument("--wgc-session-job-owner-report", type=Path, help=argparse.SUPPRESS)
    session_modes.add_argument("--wgc-visible-overlay-report", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--native-smoke-report", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--selection-smoke-input", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--selection-smoke-report", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=8765, help="仅监听 127.0.0.1；0 为自动空闲端口")
    parser.add_argument("--headless", "--no-browser", dest="headless", action="store_true", help="仅开发诊断：启动本机 HTTP 服务，不显示原生窗口")
    parser.add_argument("--no-updates", action="store_true", help="本次禁用软件更新检查（测试用）")
    parser.add_argument("--demo", action="store_true", help="仅使用虚构测试样例；不用于真实对局")
    parser.add_argument("--ready-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--self-test", action="store_true", help="校验内置模型并运行离线合成图片识别后退出")
    parser.add_argument("--report", type=Path, help="把 --self-test 结果写入 JSON 文件")
    parser.add_argument("--licenses", action="store_true", help="输出随 EXE 内置的第三方许可文本")
    parser.add_argument("--apply-update", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--update-health", type=Path, help=argparse.SUPPRESS)
    # Explicit session diagnostics accept exactly their report path. Reject every
    # normal launch option (including otherwise harmless toggles) before parsing
    # --version can exit or any ordinary application startup can occur.
    raw_args = list(sys.argv[1:] if argv is None else argv)
    session_options = {"--wgc-session-smoke-report", "--wgc-session-job-owner-report", "--wgc-visible-overlay-report"}
    if any(item.split("=", 1)[0] in session_options for item in raw_args):
        options = [item.split("=", 1)[0] for item in raw_args if item.startswith("-")]
        if len(options) != 1 or options[0] not in session_options:
            parser.error("Session WGC diagnostic cannot be combined with another launch option")
    args = parser.parse_args(raw_args)
    if args.wgc_visible_overlay_report:
        from wgc_visible_overlay_smoke import run
        return run(args.wgc_visible_overlay_report)
    if args.wgc_session_smoke_report or args.wgc_session_job_owner_report:
        from wgc_session_smoke import run, job_owner
        if args.wgc_session_job_owner_report:
            return job_owner(args.wgc_session_job_owner_report, application=True)
        return run(args.wgc_session_smoke_report, application=True)
    if args.wgc_smoke_report:
        if any((args.headless, args.native_smoke_report, args.selection_smoke_input, args.selection_smoke_report,
                args.apply_update, args.update_health, args.ready_file, args.self_test, args.version_file,
                args.licenses, args.licenses_file, args.report)):
            parser.error("WGC diagnostic cannot be combined with another launch mode")
        from wgc_smoke import run
        return run(args.wgc_smoke_report)
    if bool(args.selection_smoke_input) != bool(args.selection_smoke_report):
        parser.error("Selection diagnostic input and report must be provided together")
    if args.selection_smoke_input and (args.headless or args.native_smoke_report or args.apply_update or args.update_health or args.ready_file):
        parser.error("Selection diagnostic cannot be combined with other launch modes")
    if args.apply_update:
        from updates import apply_update
        return apply_update(args.apply_update)
    if args.version_file:
        write_json(args.version_file, {"applicationVersion": __version__, "frozen": bool(getattr(sys, "frozen", False))})
        return 0
    if args.licenses or args.licenses_file:
        if args.licenses_file:
            from contextlib import redirect_stdout
            args.licenses_file.parent.mkdir(parents=True, exist_ok=True)
            with args.licenses_file.open("w", encoding="utf-8") as output, redirect_stdout(output):
                print_licenses()
        else:
            print_licenses()
        return 0
    if args.self_test:
        result = bundled_self_test()
        if args.report:
            write_json(args.report, result)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0
    if not 0 <= args.port <= 65535:
        parser.error("端口需为 0 至 65535")
    from updates import runtime_state_dir
    from server import load_startup_data, make_server
    state_dir = runtime_state_dir()
    if not args.headless:
        from native_ui import run_native
        def ready():
            if args.update_health:
                result = bundled_self_test()
                if result.get("status") != "passed":
                    raise RuntimeError("Updated application failed bundled OCR self-test")
                from updates import mark_update_healthy
                mark_update_healthy(args.update_health)
            if args.ready_file:
                write_json(args.ready_file, {"pid": os.getpid(), "applicationVersion": __version__,
                           "frozen": bool(getattr(sys, "frozen", False)), "mode": "native-overlay"})
        return run_native(lambda: load_startup_data(state_dir / "data", demo=args.demo or bool(args.native_smoke_report or args.selection_smoke_report)),
                          state_dir=state_dir, current_executable=Path(sys.executable).resolve(),
                          current_version=__version__, frozen=bool(getattr(sys, "frozen", False)),
                          enable_updates=not (args.no_updates or args.selection_smoke_report),
                          on_ready=ready if (args.update_health or args.ready_file) else None,
                          smoke_report=args.native_smoke_report or args.selection_smoke_report,
                          smoke_screenshot=args.native_smoke_report.with_suffix(".png") if args.native_smoke_report else None,
                          selection_smoke_input=args.selection_smoke_input)
    if args.demo:
        print("正在加载明确标注的虚构演示数据…", flush=True)
    else:
        print("正在同步虎牙官方数据，首次启动可能需要几十秒；失败会保留已验证缓存。", flush=True)
    startup = load_startup_data(state_dir / "data", demo=args.demo)
    context = None if args.no_updates else {"state_dir": state_dir, "current_executable": Path(sys.executable).resolve(),
                                           "current_version": __version__, "frozen": bool(getattr(sys, "frozen", False))}
    try:
        server = make_server(startup["data"], args.port, enable_ocr=True,
                             data_status=startup["status"], update_context=context)
    except OSError:
        if args.port != 8765:
            raise
        # A second instance or another app may occupy the usual port.
        server = make_server(startup["data"], 0, enable_ocr=True,
                             data_status=startup["status"], update_context=context)
    thread = threading.Thread(target=server.serve_forever, name="vga-local-http", daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        health = complete_startup_health(url, args.update_health)
        if args.ready_file:
            write_json(args.ready_file, {"url": url, "pid": os.getpid(), "applicationVersion": __version__,
                                        "frozen": bool(getattr(sys, "frozen", False)), "health": health})
        print(f"{APP_NAME} {__version__} 已启动：{url}\n关闭此窗口或按 Ctrl+C 退出。截图识别在本机运行。", flush=True)
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return 0


def entrypoint() -> int:
    # Windowed Windows executables have no console handles. Libraries may still
    # log to them, so supply ordinary null streams without opening a console.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    # Avoid Windows locale failures when redirected by CI; no installed Python needed.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        return main()
    except Exception:
        details = traceback.format_exc()
        print(details, file=sys.stderr, flush=True)
        try:
            from updates import runtime_state_dir
            folder = runtime_state_dir() / "logs"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "last-launch-error.txt").write_text(details, encoding="utf-8")
        except Exception:
            pass
        if os.name == "nt" and getattr(sys, "frozen", False) and len(sys.argv) == 1:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "VGA乱斗助手启动失败。错误已保存到本地日志，请联系维护者。", APP_NAME, 0x10)
        # Keep source-console failures readable; never pause automation.
        if getattr(sys, "frozen", False) and len(sys.argv) == 1 and sys.stdin and sys.stdin.isatty():
            input("启动失败。请保存上面的错误信息，按 Enter 退出。")
        return 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(entrypoint())
