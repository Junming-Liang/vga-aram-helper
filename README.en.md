<!-- project-header:start -->
<p align="center"><a href="README.md">简体中文</a> | <a href="README.en.md">English</a></p>
<p align="center">
  <img src="assets/branding/vga-icon-128.png" width="112" height="112" alt="VGA ARAM Helper icon">
</p>
<h1 align="center">VGA乱斗助手</h1>
<p align="center"><strong>Champion-specific augment choices · Local screenshot OCR · Public data reference</strong></p>
<p align="center">
  <a href="https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/build-native-preview.yml"><img src="https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/build-native-preview.yml/badge.svg?branch=main&amp;event=workflow_dispatch" alt="Windows CI: latest manual build and tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-16a34a" alt="License: MIT"></a>
  <a href="app_version.py"><img src="https://img.shields.io/badge/source-v0.4.3-0891b2" alt="Source version v0.4.3"></a>
  <a href="https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.3"><img src="https://img.shields.io/badge/status-preview-d97706" alt="v0.4.3 preview"></a>
</p>
<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="WINDOWS_EXECUTABLE.md">Windows guide</a> ·
  <a href="DATA.md">Recommendations and statistics</a> ·
  <a href="CONTRIBUTING.md">Contributing</a> ·
  <a href="https://github.com/Junming-Liang/vga-aram-helper/issues">Report an issue</a>
</p>
<!-- project-header:end -->

A native Windows control panel and game overlay for champion-specific augment tiers, effects, and condition notes. The own-HUD portrait and three card titles are detected locally; stable high-confidence observations automatically display reference cards. Uncertainty keeps manual correction available.

Champion-select handoff: the highlighted own row must agree with the central champion name before carrying this session’s current assignment into its new game window. Unverified HUD identity is explicitly labeled as coming from champion select.

## Features

- **Champion-specific tiers**: displays Huya's public-source T1–T4 tiers in the original three-choice order. Missing data is labeled “暂无评级” (no rating available).
- **Automatic own champion**: matches only the bottom own-HUD portrait against Riot Data Dragon templates and requires two consistent observations.
- **Local OCR**: three exact, distinct, spatially aligned, high-confidence card titles automatically display after two consecutive safe observations; uncertainty keeps manual correction available.
- **Transparent overlay**: always-on-top reference cards with mouse click-through, toggled by `Ctrl+Alt+O`.
- **Data refresh and cache**: checks public data at startup and uses validated cached data offline.
- **Software updates**: checks stable GitHub Releases, then downloads, verifies, and installs after confirmation.

## Quick start

### Windows

1. Download the [v0.4.3 Windows x64 EXE](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.4.3/vga-aram-helper-0.4.3-windows-x64.exe) and verify the matching [SHA-256](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.4.3/SHA256SUMS.txt).
2. Place the EXE in a writable folder and double-click it.
3. Confirm the target window, start monitoring and return to the game. Champion detection is automatic by default. The first launch prepares about 5 MB of public portrait templates.

The single-file EXE includes QtWidgets, the OCR runtime, and models. See the [Windows guide](WINDOWS_EXECUTABLE.md) for setup and [License](#license) below for applicable terms. The [Release page](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.3) includes test evidence and corresponding source.

Download the current preview manually. See [UPDATES.md](UPDATES.md) for the stable-release update mechanism.

### Run from source

Use Python 3.12 x64 and run these commands in a virtual environment inside the project directory:

```sh
python -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-build.txt
python launcher.py
```

`python launcher.py --demo` loads synthetic demonstration data. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and test commands.

## Usage

- Leave automatic own-HUD detection enabled, start monitoring and return to the target window. One unambiguous standard LoL window may be preselected; capture still requires Start.
- Two consistent high-confidence own-portrait and card-title observations automatically display champion-specific tiers. The app never selects an in-game option.
- Disable automatic champion detection to correct an uncertain result manually. Unknown/changed champions, changed candidates, expired observations and focus loss hide stale cards; automatic mode waits for fresh stable evidence.
- Toggle mouse click-through with `Ctrl+Alt+O`. Stop monitoring or close the main window to end capture.

### Start in champion select

Select the client window, leave same-installation new-game handoff enabled, and click Start. The highlighted own champion row, central exact name and post-choice skin thumbnails must agree in two observations. Initial cards, hovered previews and bench choices are not treated as your assignment. Changed assignments require new evidence; this is not an irrevocable lock.

Only a unique newly started game process from the same installation may be adopted. Changing the handoff option or stopping revokes the session. Conflicting HUD identity, uncertain scenes and observation timeouts clear carried evidence; manual correction remains available. Cards explicitly identify selection-derived identity until own-HUD verification. See [champion-select scope](CHAMPION_SELECTION.md).

## Data and privacy

Reference data comes from [Huya's official public wiki](https://gametool.huya.com/league-of-legends/wiki/index.html?embed=1). Tiers use the selected champion's original records. Cards identify the source date, data-package version, and game-data version. The source date and retrieval time are recorded separately to help assess freshness. See [DATA.md](DATA.md) for formats and fields.

Capture is limited to visible client-area pixels of the selected foreground window and, when selection handoff is enabled, its unique new game window verified by installation path and process creation time. Game process memory is not read. Normal monitoring screenshots stay in local memory and are neither saved nor uploaded. Explicit synthetic diagnostics can save test images. Network requests only fetch public reference data, Riot Data Dragon portrait templates and software updates. Screenshots are never sent to those services. Riot-owned portraits stay in the local cache and are not bundled in the source or EXE.

## Preview and compatibility

v0.4.3 removes unused packaging dependencies and design-source images while preserving full offline OCR, the native overlay, automatic champion/selection handoff, data refresh and updates. The [final Windows release tests](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38383752875) passed; the published EXE is **116,559,213 bytes (111.16 MiB), 22.445% smaller than v0.4.2**. Verify the same-release SHA-256 linked above. See the [size record](WINDOWS_PACKAGE_SIZE.md) and [changelog](CHANGELOG.md).

v0.4.2 fixes overlay scaling and small-window layout. Placement uses the overlay window’s own Qt scale; compact cards preserve all three names, tiers and source metadata when space is limited. Fresh cards follow movement of the same window, while resizing waits for new recognition.

The [Windows EXE release tests](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38281910029) passed at controlled 100%, 150% and 200% application process scaling using the same EXE and a fixed 960×600-pixel original mock window. Checks cover capture/OCR, automatic champion and three-choice display, card bounds and text layout, stale-state clearing and shutdown cleanup. Champion-select recognition and session handoff also passed. The same build’s source matrix passed 35 window cases at 100%–250% scaling, including small-window hiding and recovery. Actual OS DPI, mixed-monitor transitions, fully visible 4K layouts and the cause of the reported user error remain unconfirmed.

In a small public screenshot sample, 2 of 3 own-champion examples were recognized (Samira and Katarina); Milio abstained. All 3 death/scoreboard, spectator and portrait-crop negatives abstained. This does not establish general game accuracy. See [automatic recognition scope](AUTO_RECOGNITION.md) and [per-case results](reports/hero-recognition-genuine.json).

The following are **historical v0.3.0 baseline checks**, not proof of the new automatic champion feature:

- [Native EXE tests](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38235785410): window capture, OCR, tier rendering, mouse click-through, and process lifecycle.
- [Updater transaction tests](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38239627458): local replacement of the same EXE, health checks, concurrency locking, and failure rollback.

Real LoL/Vanguard, exclusive fullscreen, and clean Windows 10/11 environments remain unverified. v0.4.3 passed same-binary native update success/concurrency/rollback; cross-version online upgrades and the in-app confirmation handoff remain untested. Public-snapshot tiers may differ from Huya's private live model; the rating methodology and applicable game policies are not fully verified, and this project has no Riot/Tencent approval. See [WINDOWS_TESTING.md](WINDOWS_TESTING.md) for detailed scope.

The EXE is not Authenticode-signed, so Windows may show an unknown-publisher warning. Verify the file hash and keep system security protections enabled.

## Development and contributing

Report problems through [Issues](https://github.com/Junming-Liang/vga-aram-helper/issues), or contribute improvements.

- [Development environment and tests](CONTRIBUTING.md)
- [Windows builds](WINDOWS_EXECUTABLE.md)
- [Data sources](SOURCE_NOTES.md) and [validation records](reports/VALIDATION.md)

## License

Original code, icons, and synthetic test data use the [MIT License](LICENSE). Qt/PySide/Shiboken use the applicable LGPLv3 option; OCR dependencies, models, and other third-party components retain their own licenses. The Release includes complete licenses, corresponding Qt source, and application source from the same commit. See [Third-party notices](THIRD_PARTY_NOTICES.md). Third-party game data is outside this project's MIT license.

Before use, read and agree to the Microsoft runtime terms in the [Release license package](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.4.3/third-party-licenses.zip). These terms apply only to the listed Microsoft DLLs, without restricting the MIT application source or Qt LGPL rights.

This is an independent implementation with no official affiliation with Riot Games, League of Legends, or Huya.
