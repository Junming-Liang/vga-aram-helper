<!-- project-header:start -->
<p align="center"><a href="README.md">简体中文</a> | <a href="README.en.md">English</a></p>
<p align="center">
  <img src="assets/branding/vga-icon-128.png" width="112" height="112" alt="VGA ARAM Helper icon">
</p>
<h1 align="center">VGA乱斗助手</h1>
<p align="center"><strong>Champion-specific augment choices · Local screenshot OCR · Public data reference</strong></p>
<p align="center">
  <a href="https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/windows-build.yml"><img src="https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/windows-build.yml/badge.svg?branch=main&amp;event=workflow_dispatch" alt="Windows CI: latest manual build and tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-16a34a" alt="License: MIT"></a>
  <a href="app_version.py"><img src="https://img.shields.io/badge/source-v0.3.0-0891b2" alt="Source version v0.3.0"></a>
  <a href="WINDOWS_EXECUTABLE.md"><img src="https://img.shields.io/badge/status-in%20development-d97706" alt="In development; no official release yet"></a>
</p>
<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="WINDOWS_EXECUTABLE.md">Windows guide</a> ·
  <a href="DATA.md">Recommendations and statistics</a> ·
  <a href="CONTRIBUTING.md">Contributing</a> ·
  <a href="https://github.com/Junming-Liang/vga-aram-helper/issues">Report an issue</a>
</p>
<!-- project-header:end -->

Double-click the Windows EXE to open the native control window and display a transparent reference overlay over a window you explicitly select. Screenshot recognition runs locally, without a separate Python installation, AI subscription, or API key. There is no official Release yet; the latest native version still awaits actual Windows EXE validation.

The CI badge reflects the latest manual build and tests, not completed in-game validation.

## Features

- **Native controls and overlay**: a QtWidgets interface with an ordinary always-on-top system window. Mouse click-through is enabled by default and can be toggled with `Ctrl+Alt+O`.
- **Explicit window monitoring**: you select the target and start monitoring. Only visible client-area pixels of the selected foreground window are captured. The app does not read game process memory, inject into the game, or install input hooks.
- **Local candidate recognition**: RapidOCR extracts augment names. Reference information appears after you check the champion and three candidates; the app does not select cards automatically.
- **Public reference data and offline cache**: startup checks Huya's official public wiki. When the network is unavailable, validated cached data is used; if there is no cache, the app clearly reports that data is unavailable.
- **Confirmed software updates**: GitHub Releases are checked, but downloading, verification, and installation start only after your confirmation.

The native overlay preserves the three cards’ original screen order and shows names, effects, condition notes, and the selected champion’s literal Huya public-source tier (T1/T2/T3/T4). The tier is copied from that champion-specific record. Missing, null, or unrecognized tiers display “暂无评级” (no rating available); there is no global-tier fallback, win-rate conversion, or invented S/A/B/C mapping. Cards are not sorted by tier, no win rates are shown, and no single best choice is dictated. The overlay identifies the source date, data-package version, and game-data version.

These are public-snapshot tiers, not a reproduction of Huya’s private live cloud model, and they may differ from its current client. The rating methodology and applicable policy scope are not fully verified; this project does not claim Riot/Tencent approval or confirmed compliance. The champion must be selected manually. The initial version targets windowed and borderless modes; exclusive fullscreen and compatibility with the real LoL client or Vanguard have not been validated. Publicly accessible data and the absence of memory reading do not imply approval by the game publisher.

## Quick start

### Windows

The portable edition has not been officially released. Check [Releases](https://github.com/Junming-Liang/vga-aram-helper/releases) for availability or follow the [Windows build workflow](https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/windows-build.yml). The target platform is Windows 10/11 x64. The single-file EXE bundles Python, QtWidgets, the OCR runtime, and models.

After obtaining a verified build, place it in a folder you can write to and double-click it. Normal use requires no browser or local URL. Close the main control window to exit. See the [Windows guide](WINDOWS_EXECUTABLE.md).

Before use, read and agree to the Microsoft runtime terms in the same Release's license ZIP. They apply only to the listed Microsoft DLLs, without restricting the MIT application source or Qt LGPL rights. See [third-party notices](THIRD_PARTY_NOTICES.md) for the complete scope.

### Run from source

Developers need Python 3.12 x64. Run the following commands in a virtual environment inside the project directory:

```sh
python -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-build.txt
python launcher.py
```

`python launcher.py --demo` uses clearly labeled fictional test data. Real window capture and the overlay are Windows-only; other systems can run pure-logic and offscreen widget tests.

The historical HTTP interface remains available as an explicit development diagnostic: `python launcher.py --headless --demo`, listening only on `127.0.0.1:8765` by default. It is not the normal user entry point, and browser tests do not replace native-window validation.

## Usage

1. After startup, wait for the public-data check and explicitly select the window to monitor.
2. Search for or select the champion manually, start monitoring, and switch back to the target window.
3. Review the left, middle, and right names produced by local OCR. Correct them manually if recognition fails.
4. After confirmation, three reference cards appear. Changing the champion, candidates, or window state invalidates and hides the previous information; confirmation is required again.
5. Use `Ctrl+Alt+O` to toggle mouse click-through. Stop monitoring or close the main window to stop capture.

Use windowed or borderless mode and avoid other windows obscuring the target. Switching away, minimizing, or a capture failure pauses the display. Brief recognition errors, scene changes, and different resolutions still require manual review. See [Data notes](DATA.md) for data formats and the statistical fields in the historical diagnostic interface.

## Data and privacy

Reference data comes from [Huya's official public wiki](https://gametool.huya.com/league-of-legends/wiki/index.html?embed=1). The app distinguishes the source date from the retrieval time; a successful download does not mean the information matches the latest game patch.

Screenshots from normal monitoring are processed only in memory. They are not saved to disk or uploaded to the cloud. Network requests retrieve public data and software updates; starting monitoring and installing software both require explicit user action. Only explicitly requested synthetic diagnostics save test images of windows created by this program. See [UPDATES.md](UPDATES.md) for the update mechanism.

## Development and contributing

Report problems through [Issues](https://github.com/Junming-Liang/vga-aram-helper/issues), or contribute improvements.

- [Development environment and tests](CONTRIBUTING.md)
- [Windows builds](WINDOWS_EXECUTABLE.md) and [test scope](WINDOWS_TESTING.md)
- [Data sources](SOURCE_NOTES.md) and [validation records](reports/VALIDATION.md)

Native Windows CI uses original mock windows to test actual capture, OCR, focus, mouse click-through, and lifecycle behavior. It cannot establish real-game performance or anti-cheat compatibility. Do not present these tests as Riot/Vanguard approval or a guarantee of account safety.

## License

Original project code, icons, and synthetic test data are licensed under the [MIT License](LICENSE). Qt/PySide/Shiboken use the applicable LGPLv3 option; OCR dependencies and models retain their own licenses. See [Third-party notices](THIRD_PARTY_NOTICES.md). Release files include complete licenses, corresponding Qt source, and application source from the same commit for inspection, modification, and rebuilding. Third-party game data is outside this project's MIT license.

This is an independent implementation, with no official affiliation with Riot Games, League of Legends, or Huya. The EXE is not Authenticode-signed. Check its SHA-256 after downloading, and do not disable security protections to bypass warnings.
