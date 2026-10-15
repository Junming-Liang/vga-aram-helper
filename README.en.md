<!-- project-header:start -->
<p align="center"><a href="README.md">简体中文</a> | <a href="README.en.md">English</a></p>
<p align="center">
  <img src="assets/branding/vga-icon-128.png" width="112" height="112" alt="VGA ARAM Helper icon">
</p>
<h1 align="center">VGA ARAM Helper · League of Legends ARAM: Mayhem</h1>
<p align="center"><strong>Augment recommendations · Champion-specific tiers · Local screenshot OCR</strong></p>
<p align="center">
  <a href="https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/build-native-preview.yml"><img src="https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/build-native-preview.yml/badge.svg?branch=main&amp;event=workflow_dispatch" alt="Windows CI: latest manual build and tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-16a34a" alt="License: MIT"></a>
  <a href="app_version.py"><img src="https://img.shields.io/badge/source-v0.4.7-0891b2" alt="Source version v0.4.7"></a>
  <a href="https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.7"><img src="https://img.shields.io/badge/status-preview-d97706" alt="v0.4.7 preview"></a>
</p>
<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="WINDOWS_EXECUTABLE.md">Windows guide</a> ·
  <a href="DATA.md">Recommendations and statistics</a> ·
  <a href="CONTRIBUTING.md">Contributing</a> ·
  <a href="https://github.com/Junming-Liang/vga-aram-helper/issues">Report an issue</a>
</p>
<!-- project-header:end -->

VGA ARAM Helper (VGA乱斗助手) is an open-source Windows helper for **League of Legends (LoL) ARAM: Mayhem**, known in Chinese as **英雄联盟海克斯大乱斗**. Its native control panel and game overlay provide champion-specific augment tiers, effects, and condition notes for three-choice augment selections.

The own-HUD portrait and three card titles are detected locally; stable high-confidence observations automatically display reference cards. Uncertainty keeps manual correction available.

Champion-select handoff: the highlighted own row must agree with the central champion name before carrying this session’s current assignment into its new game window. Unverified HUD identity is explicitly labeled as coming from champion select.

## ARAM: Mayhem helper features

- **Champion-specific augment tiers**: displays Huya's public-source T1–T4 tiers in the original three-choice order. Missing data is labeled “暂无评级” (no rating available).
- **Automatic own champion**: matches only the bottom own-HUD portrait against Riot Data Dragon templates and requires two consistent observations.
- **Local OCR**: three exact, distinct, spatially aligned, high-confidence card titles automatically display after two consecutive safe observations; uncertainty keeps manual correction available.
- **Compact native UI**: v0.4.7 has a light dashboard, reachable Start/Stop, secondary Settings/Check reference/About pages, and three screen-ordered name+tier cards with click-through and `Ctrl+Alt+O`. Overlays exceeding half the client height hide. A separate exact-name dictionary view provides complete descriptions without claiming recognition or confirmation.
- **Data refresh and cache**: checks public data at startup and uses validated cached data offline.
- **Software updates**: checks stable GitHub Releases, then downloads, verifies, and installs after confirmation.

## Quick start

### Windows

1. Download the [v0.4.7 Windows x64 EXE](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.4.7/vga-aram-helper-0.4.7-windows-x64.exe) and verify the matching [SHA-256](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.4.7/SHA256SUMS.txt).
2. Place the EXE in a writable folder and double-click it.
3. Keep automatic League discovery selected and click Start. The helper minimizes and waits for or follows your client/game without selecting a window. The first launch prepares about 5 MB of public portrait templates.

The single-file EXE includes QtWidgets, the OCR runtime, and models. See the [Windows guide](WINDOWS_EXECUTABLE.md) for setup and [License](#license) below for applicable terms. The [Release page](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.7) includes test evidence and corresponding source.

The v0.4.7 preview is published. Download it manually and verify the same-release manifest and SHA-256; stable OTA excludes prereleases. See [UPDATES.md](UPDATES.md).

### Run from source

Use Python 3.12 x64 and run these commands in a virtual environment inside the project directory:

```sh
python -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-build.txt
python launcher.py
```

`python launcher.py --demo` loads synthetic demonstration data. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and test commands.

## v0.4.7: light dashboard and capture improvements

[v0.4.7](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.7) was published on 2026-10-15 after [Windows release run #48](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38707221941) passed every required source, frozen EXE, 100%/150%/200% product capture/overlay, selection, update, performance, size and source/license gate. It unifies the dashboard and compact overlay in the selected light B direction. The exact tested EXE is **106,858,822 bytes (101.91 MiB)**; see [release identity and limits](WINDOWS_EXECUTABLE.md).

- Each capture cycle schedules the next after completion. Strict pixel and identity rechecks can restore an explicitly labeled previous-candidates view during inference, avoiding unnecessary prolonged hiding. Confirmed references wait 700 ms before another cycle; unstable observations wait 200 ms. These are scheduling intervals, not guaranteed capture latency or game frame rates.
- Champion select has a separate public-source overall champion T1–T5 reference labeled provisional and not HUD-verified; augment tiers remain T1–T4. The control panel retains “Last candidates · final choice unknown.” A disappearing selection screen never identifies the chosen augment.
- Persistent capture reuses the verified window session and still hides the overlay before readback. The idle frame pool may retain the authorized window's full GPU surface; CPU readback is request-ROI-only. Revocation starts asynchronous cleanup without a 50 ms exit guarantee under system stalls. The normal Windows capture border remains enabled. True exclusive fullscreen, live LoL/Vanguard and automatic final-choice detection remain unverified. See [feedback fixes and evidence limits](PLAY_FEEDBACK_FIXES.md).

- The dashboard shows the current champion, monitoring state and left/center/right candidates. One primary monitoring action switches between Start and Stop; secondary pages retain a Stop action while monitoring.
- Settings (“设置”) contains window connection, champion correction and capture-region controls. Check reference (“核对资料”) provides candidate correction, explicit confirmation and full exact-name lookup. About (“关于”) exposes the full source date, data-package and game-data versions, update status and compatibility limits. Back (“返回”) returns to the dashboard. Lookup never confirms or replaces the current monitoring result.
- The compact overlay shows names and literal tiers with “虎牙公开源” (Huya public source) or “虚构演示” (synthetic demo) attribution, preserving original order, click-through and the half-client-height limit. Visible tier pills (for example `T1`) and accessible source labels (`虎牙公开源评级：T1` or `虚构源评级（演示）：T1`) are separately verified evidence fields. Full source metadata and the statement that these are neither Riot ratings nor Riot approval remain reachable in About.

## Usage

- Keep automatic window and own-HUD detection enabled, click Start and return to the game. A missing, minimized or occluded game waits and retries; ambiguous windows or an unverified installation show an explicit status.
- Two consistent high-confidence own-portrait and card-title observations automatically display champion-specific tiers. The app never selects an in-game option.
- Disable automatic champion detection to correct an uncertain result manually. Unknown/changed champions, changed candidates, expired observations and focus loss hide stale cards; automatic mode waits for fresh stable evidence.
- Toggle mouse click-through with `Ctrl+Alt+O`. Stop monitoring or close the main window to end capture.

### Start in champion select

In v0.4.7, keep the default automatic League discovery and click Start. The helper minimizes and follows the same installation’s client/game, including an already running match or later launch. The highlighted own champion row, central exact name and post-choice skin thumbnails must agree in two observations. Initial cards, hovered previews and bench choices are not treated as your assignment. Changed assignments require new evidence; this is not an irrevocable lock.

Champion-select identity carries only into a unique newly started game process from the same installation. An already running game can still be bound automatically, but requires fresh own-HUD confirmation. Changing the handoff option or stopping revokes the session. Conflicting HUD identity, uncertain scenes and observation timeouts clear carried evidence; manual correction remains available. Cards explicitly identify selection-derived identity until own-HUD verification. See [champion-select scope](CHAMPION_SELECTION.md).

## Data and privacy

Reference data comes from [Huya's official public wiki](https://gametool.huya.com/league-of-legends/wiki/index.html?embed=1). Tiers use the selected champion's original records. Full cards identify the source date, data-package version, and game-data version. The control panel shows the source date and game-data version. Compact cards retain per-card source-tier attribution; source date and game-data version remain available in the control panel. The source date and retrieval time are recorded separately to help assess freshness. See [DATA.md](DATA.md) for formats and fields.

Automatic mode binds one verified League installation and captures only the foreground target’s visible client area. Advanced manual diagnostics require an explicitly selected window and Start. Client/game transitions check the installation path, window identity and process creation time. Game process memory is not read. Normal monitoring screenshots stay in local memory and are neither saved nor uploaded. Explicit synthetic diagnostics can save test images. Application-initiated network requests fetch public reference data, Riot Data Dragon portrait templates and software updates. Screenshots are never sent to those services. Riot-owned portraits stay in the local cache and are not bundled in the source or EXE.

v0.4.4 sets `ORT_DISABLE_TELEMETRY=1` before ONNX Runtime imports/initialization and keeps the API opt-out. [Official ORT 1.31.0 documentation](https://github.com/microsoft/onnxruntime/blob/v1.31.0/docs/Privacy.md) explains that the API can run after minimal initialization. This hardens the opt-out; it does not establish prior transmission or provide a network firewall or comprehensive outbound audit.

## Preview and compatibility

[v0.4.7](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.7) is available as a non-latest prerelease and requires manual download. The [current validation scope](reports/VALIDATION.md) is separate from the historical releases below.

### Historical v0.4.6 and earlier releases

[v0.4.6 preview](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.6) passed every gate in [Windows release run #23](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38531070525). It adds explicit-HWND Windows Graphics Capture, asynchronous capture, exact-first Chinese matching, bounded unchanged-crop OCR reuse, and a redesigned native control panel with compact cards. See [implementation and validation scope](REFERENCE_OPTIMIZATION.md).

Source tests passed three-scale WGC and five-scale overlay layout. Separately, the same final EXE passed three-scale frozen WGC, native capture/overlay at 100%/150%/200%, independent OCR confirmation/reuse, selection handoff, same-version update/concurrency/rollback, and source/license verification. The EXE is **106,553,042 bytes (101.62 MiB)**, SHA-256 `0c2aef8e7759c149d6da90348d2ba065590c7e39b5f1522906d7e658b1b08d3a`, from source/tag `f7ce587ee9a93fc509fd4b4e5b6a1cce150b2423`. It remains a prerelease excluded from stable OTA. Original owned-window tests do not establish real LoL/Vanguard compatibility.

Historical [v0.4.5 Windows release validation](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38447380079) passed every gate and published the preview. The EXE is **106,399,997 bytes (101.47 MiB)**, retaining the existing offline models and minimal OpenCV recipe. Verify the matching SHA-256 after downloading; see the [size and hash record](WINDOWS_PACKAGE_SIZE.md).

That v0.4.5 real-Windows source fixture passed waiting, client/game transitions, pre-existing games, restart, HWND recreation, minimize/restore, blank-frame fallback and occlusion rejection. Every capture reported mean-channel error 0.0 against original test images. Publisher trust is injected only for the test-owned executables, so this does not verify real League signatures or compatibility. The same run passed seven native cache sharing-lock/diagnostic tests and final-EXE acceptance at 100%/150%/200% application scale, OCR, selection handoff and local update transactions. The exact owner/cause of the historical WinError 5 remains unknown; the new portrait-cache diagnostics are local and never uploaded automatically.

See the [validation record](reports/VALIDATION.md) for scope. Historical size and timing results remain in the [recipe history](WINDOWS_MINIMAL_OPENCV_EXPERIMENT.md) and [changelog](CHANGELOG.md); they do not establish real-game performance.

v0.4.2 fixes the confirmed Qt logical/Win32 physical coordinate mismatch and rigid overlay layout in small windows. Placement uses the overlay window’s own Qt scale; compact cards preserve all three names, tiers and source metadata when space is limited. Fresh cards follow movement of the same window, while resizing waits for new recognition.

The [Windows EXE release tests](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38281910029) passed at controlled 100%, 150% and 200% application process scaling using the same EXE and a fixed 960×600-pixel original mock window. Checks cover capture/OCR, automatic champion and three-choice display, card bounds and text layout, stale-state clearing and shutdown cleanup. Champion-select recognition and session handoff also passed. The same build’s source matrix passed 35 window cases at 100%–250% scaling, including small-window hiding and recovery. Actual OS DPI, mixed-monitor transitions, fully visible 4K layouts and the cause of the reported user error remain unconfirmed.

In the small public screenshot sample actually rerun with current v0.4.7 source on Linux using the official wheel, 2 of 3 own-champion examples were recognized (Samira and Katarina); Milio abstained. All 3 death/scoreboard, spectator and portrait-crop negatives abstained. This does not establish general game accuracy or Windows custom-wheel recognition performance. See [automatic recognition scope](AUTO_RECOGNITION.md) and [per-case results](reports/hero-recognition-genuine.json).

The following are **historical v0.3.0 baseline checks**, not proof of the new automatic champion feature:

- [Native EXE tests](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38235785410): window capture, OCR, tier rendering, mouse click-through, and process lifecycle.
- [Updater transaction tests](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38239627458): local replacement of the same EXE, health checks, concurrency locking, and failure rollback.

Real LoL/Vanguard, exclusive fullscreen, and clean Windows 10/11 environments remain unverified. v0.4.7 passed same-binary native update success/concurrency/rollback; cross-version online upgrades and the in-app confirmation handoff remain untested. Public-snapshot tiers may differ from Huya's private live model; the rating methodology and applicable game policies are not fully verified, and this project has no Riot/Tencent approval. See [WINDOWS_TESTING.md](WINDOWS_TESTING.md) for detailed scope.

The EXE is not Authenticode-signed, so Windows may show an unknown-publisher warning. Verify the file hash and keep system security protections enabled.

## Development and contributing

Report problems through [Issues](https://github.com/Junming-Liang/vga-aram-helper/issues), or contribute improvements.

- [Development environment and tests](CONTRIBUTING.md)
- [Windows builds](WINDOWS_EXECUTABLE.md)
- [Data sources](SOURCE_NOTES.md) and [validation records](reports/VALIDATION.md)

## License

Original code, icons, and synthetic test data use the [MIT License](LICENSE). Qt/PySide/Shiboken use the applicable LGPLv3 option; OCR dependencies, models, and other third-party components retain their own licenses. The Release includes complete licenses, corresponding Qt source, and application source from the same commit. See [Third-party notices](THIRD_PARTY_NOTICES.md). Third-party game data is outside this project's MIT license.

Before use, read and agree to the Microsoft runtime terms in the [Release license package](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.4.7/third-party-licenses.zip). These terms apply only to the listed Microsoft DLLs, without restricting the MIT application source or Qt LGPL rights. The custom OpenCV and WGC helper `/MT` builds also embed Microsoft release CRT object code under separate applicable Microsoft terms; servicing it requires rebuilding. See the [runtime scope notice](THIRD_PARTY_NOTICES.md#microsoft-windows-runtime-components).

This is an independent implementation with no official affiliation with Riot Games, League of Legends, or Huya.
