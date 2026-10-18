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
  <a href="app_version.py"><img src="https://img.shields.io/badge/source-v0.4.15-0891b2" alt="Source version v0.4.15"></a>
  <a href="https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.14"><img src="https://img.shields.io/badge/status-preview-d97706" alt="v0.4.14 preview"></a>
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

Champion-select handoff: when a client is detected, click “开启本机选人识别” to authorize the read-only local selection API for this launch. Screenshot fallback remains available when disabled or unavailable; it requires agreement between the highlighted own row and central champion name before carrying this session’s assignment into its new game window. Unverified HUD identity is explicitly labeled as coming from champion select.

## ARAM: Mayhem helper features

- **Champion-specific augment tiers**: displays Huya's public-source T1–T4 tiers in the original three-choice order. Missing data is labeled “暂无评级” (no rating available).
- **Automatic own champion**: the optional read-only current-game API check is on by default, with own-HUD portrait matching retained. Independently confirmed identity can survive death countdowns within the same verified game session.
- **Local OCR**: spatially verified, high-confidence slots can display after two independent fresh observations; unknown slots stay ungraded and never borrow previous results. Manual correction remains available.
- **Above-card tiers**: three independently bounded regions preserve offer order and show tiers, identity provenance and available combo hints. Full names/descriptions remain in the control window; unverified card bounds hide the badges. Mouse passthrough is enabled.
- **Data refresh and cache**: checks public data at startup and uses validated cached data offline.
- **Software updates**: checks stable GitHub Releases, then downloads, verifies, and installs after confirmation.

## Quick start

### Windows

1. Download the [v0.4.14 Windows x64 EXE](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.4.14/vga-aram-helper-0.4.14-windows-x64.exe) and verify the matching [SHA-256](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.4.14/SHA256SUMS.txt).
2. Place the EXE in a writable folder and double-click it.
3. Keep automatic League discovery selected and click Start. The control window stays visible by default and waits for or follows your client/game without selecting a window. The first launch prepares about 5 MB of public portrait templates.
4. To use the selection API, click “开启本机选人识别” in the dashboard after client detection. Consent lasts for this launch only and is off again after restart.

The single-file EXE includes QtWidgets, the OCR runtime, and models. See the [Windows guide](WINDOWS_EXECUTABLE.md) for setup and [License](#license) below for applicable terms. The [Release page](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.14) includes test evidence and corresponding source.

The v0.4.14 diagnostic preview is published, but flicker and initial recognition failures have been reported. The local v0.4.15 candidate is not available to download. Download previews manually and verify the same-release manifest and SHA-256; stable OTA excludes prereleases. See [UPDATES.md](UPDATES.md).

### Run from source

Use Python 3.12 x64 and run these commands in a virtual environment inside the project directory:

```sh
python -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-build.txt
python launcher.py
```

`python launcher.py --demo` loads synthetic demonstration data. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and test commands.

## v0.4.15: regression recovery candidate, local preparation pending Windows acceptance

This candidate addresses three reproducible defects: warm-cache refresh replaces the recognition model even when content is equivalent; a fixed idle pause can consume the four-second refresh budget; and cold-start API canonical lookup waits for all portraits. Equivalent content preserves the model object, actual changes wait for a safe boundary, measured capture/inference cost determines the pause with a 50 ms floor and unchanged four-second expiry, and a complete validated official roster can supply API lookup before the image bank is ready. See the [regression investigation and validation limits](REGRESSION_RECOVERY.md).

v0.4.15 is prepared locally only; no Windows EXE has been built or published. Controlled Qt/OCR regressions do not replace complete same-EXE Windows or actual-game acceptance. Manual validation still defaults to `publish_preview=false`. The download entry points to published v0.4.14 with reported issues and does not provide this candidate.

## v0.4.14: startup recovery diagnostic prerelease, published with regression feedback

The [v0.4.14 diagnostic prerelease](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.14) is published. It includes capped empty-bank download retries, validated-cache-first startup, an in-memory canonical-map fallback after disk-write failure, and safe rejection of malformed roster/cache objects. See the historical [recovery audit](STARTUP_RECOVERY.md).

After publication, the user again reported flicker and initial recognition failure. No incident diagnostic ZIP was supplied, so the installed version, game stage and field cause remain unconfirmed. The v0.4.15 changes address controlled reproductions and do not establish that the user's field symptoms are solved.

## v0.4.13: semantic recheck diagnostic baseline

The source candidate verifies fresh same-frame title semantics rather than revoking grades solely because background pixels in a title band changed. Partial candidates retain independently verified known slots while unknown slots remain ungraded. Historical grades retain only their original four-second deadline; real rerolls may remain until fresh OCR returns, not instantaneous detection. Separate critical-event retention and selection gate diagnostics stay local. At that stage, download links retained v0.4.12; actual-game behavior was unverified. See [candidate verification](reports/SEMANTIC_RECHECK_DIAGNOSTICS.md).

## v0.4.12: capture stability diagnostic prerelease, published

[v0.4.12 diagnostic prerelease](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.12) was published on 2026-10-17 after the [complete Windows release run](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/39037126275) passed every existing gate. The release commit is `966f79ea7305d716d6ae854432cf20a08344e985`. The downloaded EXE is **107,058,338 bytes**, with SHA-256 `cf7564424e5981f0c56004547301acb78cd3f3c2896fe60a91b0c95d5f39aa3b`, matching its same-release manifest and checksums.

This diagnostic build enables switchable local logs by default, bounded to 768 KiB (3 × 256 KiB). Export replaces one local ZIP and nothing uploads automatically. It remains a non-latest prerelease requiring manual download. Actual-game flashing, rechecking and latency remain unverified; passing these gates does not establish that the reported problem is solved. See [diagnostic scope](BOUNDED_DIAGNOSTICS.md).

## v0.4.11: capture transitions and selection recognition

[v0.4.11](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.11) was published on 2026-10-17 after the [complete Windows release run](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/39025025768) passed every required gate. Capture cleanup waits now preserve a pending visible-mode request, addressing a reproducible path to repeated hiding and candidate rechecks. Freshness and occlusion checks remain enforced.

Authorized selection API reads run independently of screenshot availability. API failure schedules a separate screenshot fallback and reports a bounded reason. The dashboard now provides “开启本机选人识别”; this separate permission remains off by default and lasts for the current launch only.

The same final EXE passed three-scale capture/overlay, selection handoff and OTA rollback checks. Real-client and user-game behavior still require validation. The later v0.4.12 diagnostic source separately reran the static-image fixtures on 2026-10-17; those results do not add live-game evidence for the v0.4.11 EXE. See [validation scope](reports/VALIDATION.md).

## v0.4.10: same-game identity and above-card tiers

[v0.4.10](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.10) was published on 2026-10-17 after [Windows release run #71](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/39015163655) passed every required gate: source and same-EXE native capture/tier checks at three scales, five-scale layout, partial-slot recovery, selection handoff, same-binary OTA, and final source/license validation.

Read-only current-game identity is on by default with an Off switch. Reliable identity survives death countdowns within the same verified game session; offers still require independent fresh confirmation and retain their four-second expiry. The separate selection-client API remains off by default. Three independently bounded above-card badges show tiers and available public-source combo hints. Automatic minimization is optional and off by default.

This non-latest prerelease requires manual download; stable `/releases/latest` OTA excludes it. Owned synthetic-window acceptance does not establish real LoL/Vanguard, user-game or current-client API compatibility, eliminate all flicker, or demonstrate faster raw OCR. See [implementation and limits](DEATH_IDENTITY_AND_CARD_BADGES.md).

## v0.4.9: window handoff, per-slot recognition and diagnostics

[v0.4.9](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.9) was published on 2026-10-16 after [Windows release run #62](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38946465944) passed every required gate, including the same EXE at 100%/150%/200%, partial-slot display/recovery, selection handoff, same-binary OTA and final source/license checks.

Stable window identity now survives caption changes and untitled windows under existing executable/signature guards. A bounded HUD/OCR worker is reused, independently confirmed slots can appear while unknown slots stay ungraded, and diagnostic reasons distinguish window/capture/hero/title/tier failures. Two optional read-only local API identity helpers require separate, default-off, current-session consent.

The EXE is **106,971,324 bytes (102.02 MiB)**. Real LoL/Vanguard, the user's match, and current-client compatibility of the optional APIs remain unverified; passing owned fixtures does not establish that the reported latency/flicker is resolved. This is a non-latest prerelease: stable `/releases/latest` OTA does not discover it, so download manually. See [release identity](WINDOWS_EXECUTABLE.md) and [validation scope](reports/VALIDATION.md).

## v0.4.8: display expiry and guarded visible capture

[v0.4.8](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.8) was published on 2026-10-15 after [Windows release run #55](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38793233284) passed every required source, frozen EXE, 100%/150%/200% product capture/overlay, selection, update, performance, size and source/license gate. The exact tested EXE is **106,925,126 bytes (101.97 MiB)**; see [release identity and limits](WINDOWS_EXECUTABLE.md).

- Four-second presentation expiry hides old references without cancelling a newer, still-fresh inference under unchanged authority. Focus, identity, geometry, permission and Stop still revoke work. Completion-driven scheduling can shorten the usual 700/200 ms waits to preserve observation freshness.
- Guarded visible capture is enabled by default at the normal entry point, subject to runtime proof for the exact owned opaque overlay, token/styles, `WDA_EXCLUDEFROMCAPTURE=0x11`, target identity, foreground and ROI. Previous candidates stay explicitly labeled while rechecking; completed fresh recognition hides them when it reports changed candidate/champion identity or uncertainty; harmless ROI animation with unchanged recognized identity does not require hiding. Legacy strict-hidden paths and refusal/cleanup rules remain. Source and the same frozen EXE passed three-scale normal-entry changed-ROI and pixel-exclusion checks.
- The dashboard uses verified cached champion portraits and public-source overall T1–T5 tiers. Champion-select identity stays provisional until HUD verification; augment tiers remain T1–T4. “Last candidates · final choice unknown” never infers the final choice from a disappearing screen.
- This diagnostic build enables local logs by default, with an obvious Settings toggle and local-only ZIP export. Three rotating 256 KiB files contain correlated frame IDs, hide reasons, phase timings, confirmation gates and matched catalog hero/augment names. Screenshots, raw OCR, player/account identity, credentials and paths are excluded. Export reports truncation; nothing uploads automatically. See [diagnostics](BOUNDED_DIAGNOSTICS.md).
- The normal Windows capture border, request-ROI-only CPU readback, idle GPU surfaces and asynchronous cleanup limits remain. The reported later-round flashing in borderless gameplay, live LoL/Vanguard, true exclusive fullscreen and automatic final-choice detection remain unverified. See [feedback fixes and evidence limits](PLAY_FEEDBACK_FIXES.md).

- The dashboard shows the current champion, monitoring state and left/center/right candidates. One primary monitoring action switches between Start and Stop; secondary pages retain a Stop action while monitoring.
- Settings (“设置”) contains window connection, champion correction and capture-region controls. Check reference (“核对资料”) provides candidate correction, explicit confirmation and full exact-name lookup. About (“关于”) exposes the full source date, data-package and game-data versions, update status and compatibility limits. Back (“返回”) returns to the dashboard. Lookup never confirms or replaces the current monitoring result.
- The compact overlay shows names and literal tiers with “虎牙公开源” (Huya public source) or “虚构演示” (synthetic demo) attribution, preserving original order, click-through and the half-client-height limit. Visible tier pills (for example `T1`) and accessible source labels (`虎牙公开源评级：T1` or `虚构源评级（演示）：T1`) are separately verified evidence fields. Full source metadata and the statement that these are neither Riot ratings nor Riot approval remain reachable in About.

## Usage

- Keep automatic window and current-game identity checks enabled, click Start and return to the game. A missing, minimized or occluded game waits and retries; ambiguous windows or an unverified installation show an explicit status.
- Independently confirmed game identity and consecutive fresh card evidence enable champion-specific tiers; reliable same-game identity can survive death countdowns. The app never selects an in-game option.
- Disable automatic champion detection to correct an uncertain result manually. Conflicting or unverified identity, changed candidates, expired observations and focus loss hide stale cards; automatic mode waits for fresh evidence.
- `Ctrl+Alt+O` changes interaction/reference settings; candidate badges always remain click-through. Stop monitoring or close the main window to end capture.

### Start in champion select

In v0.4.8, keep the default automatic League discovery and click Start. The helper minimizes and follows the same installation’s client/game, including an already running match or later launch. The highlighted own champion row, central exact name and post-choice skin thumbnails must agree in two observations. Initial cards, hovered previews and bench choices are not treated as your assignment. Changed assignments require new evidence; this is not an irrevocable lock.

Champion-select identity carries only into a unique newly started game process from the same installation. An already running game can still be bound automatically, but requires fresh own-HUD confirmation. Changing the handoff option or stopping revokes the session. Conflicting HUD identity, uncertain scenes and observation timeouts clear carried evidence; manual correction remains available. Cards explicitly identify selection-derived identity until own-HUD verification. See [champion-select scope](CHAMPION_SELECTION.md).

## Data and privacy

Reference data comes from [Huya's official public wiki](https://gametool.huya.com/league-of-legends/wiki/index.html?embed=1). Tiers use the selected champion's original records. Full cards identify the source date, data-package version, and game-data version. The control panel shows the source date and game-data version. Compact cards retain per-card source-tier attribution; source date and game-data version remain available in the control panel. The source date and retrieval time are recorded separately to help assess freshness. See [DATA.md](DATA.md) for formats and fields.

Automatic mode binds one verified League installation and captures only the foreground target’s visible client area. Advanced manual diagnostics require an explicitly selected window and Start. Client/game transitions check the installation path, window identity and process creation time. Game process memory is not read. Normal monitoring screenshots stay in local memory and are neither saved nor uploaded. Explicit synthetic diagnostics can save test images. Application-initiated network requests fetch public reference data, Riot Data Dragon portrait templates and software updates. Screenshots are never sent to those services. Riot-owned portraits stay in the local cache and are not bundled in the source or EXE.

v0.4.4 sets `ORT_DISABLE_TELEMETRY=1` before ONNX Runtime imports/initialization and keeps the API opt-out. [Official ORT 1.31.0 documentation](https://github.com/microsoft/onnxruntime/blob/v1.31.0/docs/Privacy.md) explains that the API can run after minimal initialization. This hardens the opt-out; it does not establish prior transmission or provide a network firewall or comprehensive outbound audit.

## Preview and compatibility

[v0.4.14](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.14) is available as a non-latest diagnostic prerelease, with reported flicker and initial recognition failures. The local v0.4.15 candidate is not published. Manual download is required. The [current validation scope](reports/VALIDATION.md) is separate from the historical releases below.

### Historical v0.4.7 and earlier releases

[v0.4.7](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.7) passed [release run #48](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38707221941), introducing the light dashboard and accepted-frame capture rechecks. Its original identity and measurements remain in the [validation history](reports/VALIDATION.md).

[v0.4.6 preview](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.6) passed every gate in [Windows release run #23](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38531070525). It adds explicit-HWND Windows Graphics Capture, asynchronous capture, exact-first Chinese matching, bounded unchanged-crop OCR reuse, and a redesigned native control panel with compact cards. See [implementation and validation scope](REFERENCE_OPTIMIZATION.md).

Source tests passed three-scale WGC and five-scale overlay layout. Separately, the same final EXE passed three-scale frozen WGC, native capture/overlay at 100%/150%/200%, independent OCR confirmation/reuse, selection handoff, same-version update/concurrency/rollback, and source/license verification. The EXE is **106,553,042 bytes (101.62 MiB)**, SHA-256 `0c2aef8e7759c149d6da90348d2ba065590c7e39b5f1522906d7e658b1b08d3a`, from source/tag `f7ce587ee9a93fc509fd4b4e5b6a1cce150b2423`. It remains a prerelease excluded from stable OTA. Original owned-window tests do not establish real LoL/Vanguard compatibility.

Historical [v0.4.5 Windows release validation](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38447380079) passed every gate and published the preview. The EXE is **106,399,997 bytes (101.47 MiB)**, retaining the existing offline models and minimal OpenCV recipe. Verify the matching SHA-256 after downloading; see the [size and hash record](WINDOWS_PACKAGE_SIZE.md).

That v0.4.5 real-Windows source fixture passed waiting, client/game transitions, pre-existing games, restart, HWND recreation, minimize/restore, blank-frame fallback and occlusion rejection. Every capture reported mean-channel error 0.0 against original test images. Publisher trust is injected only for the test-owned executables, so this does not verify real League signatures or compatibility. The same run passed seven native cache sharing-lock/diagnostic tests and final-EXE acceptance at 100%/150%/200% application scale, OCR, selection handoff and local update transactions. The exact owner/cause of the historical WinError 5 remains unknown; the new portrait-cache diagnostics are local and never uploaded automatically.

See the [validation record](reports/VALIDATION.md) for scope. Historical size and timing results remain in the [recipe history](WINDOWS_MINIMAL_OPENCV_EXPERIMENT.md) and [changelog](CHANGELOG.md); they do not establish real-game performance.

v0.4.2 fixes the confirmed Qt logical/Win32 physical coordinate mismatch and rigid overlay layout in small windows. Placement uses the overlay window’s own Qt scale; compact cards preserve all three names, tiers and source metadata when space is limited. Fresh cards follow movement of the same window, while resizing waits for new recognition.

The [Windows EXE release tests](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38281910029) passed at controlled 100%, 150% and 200% application process scaling using the same EXE and a fixed 960×600-pixel original mock window. Checks cover capture/OCR, automatic champion and three-choice display, card bounds and text layout, stale-state clearing and shutdown cleanup. Champion-select recognition and session handoff also passed. The same build’s source matrix passed 35 window cases at 100%–250% scaling, including small-window hiding and recovery. Actual OS DPI, mixed-monitor transitions, fully visible 4K layouts and the cause of the reported user error remain unconfirmed.

In the public screenshot sample rerun against the v0.4.12 diagnostic source on Linux using the official wheel, 2 of 3 own-champion examples were recognized (Samira and Katarina); Milio abstained. All 3 death/scoreboard, spectator and portrait-crop negatives abstained. The original validation runners regenerated source-bound reports on 2026-10-17, without redistributing images. This does not establish general game accuracy or Windows custom-wheel recognition performance. See [automatic recognition scope](AUTO_RECOGNITION.md) and [per-case results](reports/hero-recognition-genuine.json).

The following are **historical v0.3.0 baseline checks**, not proof of the new automatic champion feature:

- [Native EXE tests](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38235785410): window capture, OCR, tier rendering, mouse click-through, and process lifecycle.
- [Updater transaction tests](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38239627458): local replacement of the same EXE, health checks, concurrency locking, and failure rollback.

Real LoL/Vanguard, exclusive fullscreen, and clean Windows 10/11 environments remain unverified. v0.4.8 passed same-binary native update success/concurrency/rollback; cross-version online upgrades and the in-app confirmation handoff remain untested. Public-snapshot tiers may differ from Huya's private live model; the rating methodology and applicable game policies are not fully verified, and this project has no Riot/Tencent approval. See [WINDOWS_TESTING.md](WINDOWS_TESTING.md) for detailed scope.

The EXE is not Authenticode-signed, so Windows may show an unknown-publisher warning. Verify the file hash and keep system security protections enabled.

## Development and contributing

Report problems through [Issues](https://github.com/Junming-Liang/vga-aram-helper/issues), or contribute improvements.

- [Development environment and tests](CONTRIBUTING.md)
- [Windows builds](WINDOWS_EXECUTABLE.md)
- [Data sources](SOURCE_NOTES.md) and [validation records](reports/VALIDATION.md)

## License

Original code, icons, and synthetic test data use the [MIT License](LICENSE). Qt/PySide/Shiboken use the applicable LGPLv3 option; OCR dependencies, models, and other third-party components retain their own licenses. The Release includes complete licenses, corresponding Qt source, and application source from the same commit. See [Third-party notices](THIRD_PARTY_NOTICES.md). Third-party game data is outside this project's MIT license.

Before use, read and agree to the Microsoft runtime terms in the [Release license package](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.4.14/third-party-licenses.zip). These terms apply only to the listed Microsoft DLLs, without restricting the MIT application source or Qt LGPL rights. The custom OpenCV and WGC helper `/MT` builds also embed Microsoft release CRT object code under separate applicable Microsoft terms; servicing it requires rebuilding. See the [runtime scope notice](THIRD_PARTY_NOTICES.md#microsoft-windows-runtime-components).

This is an independent implementation with no official affiliation with Riot Games, League of Legends, or Huya.
