# Champion-select handoff / 选人衔接

Experimental screenshot-only selection recognition. In v0.4.5 source, keep automatic League discovery selected and explicitly Start with handoff enabled. No nickname setup or hero preselection is required. The [v0.4.1 Windows EXE gate](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38265698203) passed with original owned client/game fixtures, actual window metadata and local OCR. This validates the synthetic session flow; current real-client and live-game compatibility remain unverified.

## Evidence and limits

- Canonical hero text in exactly one gold-highlighted team row must agree with the central hero name. A row of small post-choice skin thumbnails is required. Two fresh observations establish a **current assignment**, never an irrevocable lock.
- Initial Champion Cards, hovered cards, bench choices and ambiguous rows do not establish assignment. Gold-row highlighting is an empirical UI anchor, not an official API contract. Unknown layouts abstain.
- Local still-image check: one July 2025 Traditional Chinese post-choice screenshot containing third-party client modifications recognized Cho’Gath; three initial-card images abstained. The three negatives represent **two distinct scenes**, with one resized/original pair. This is not current stock-client or live trade/cancel accuracy proof. [Per-case report](reports/champion-select-genuine.json).
- Selection-derived identity can show reference cards after the authorized game handoff while explicitly labeled `来自本局选人 · HUD未复核`. Matching own HUD upgrades the provenance; a conflicting HUD clears it.
- The first game-scene anchor must be a confident own-HUD match or three high-confidence exact augment titles. Once carried identity is in use, missing both anchors clears it. Loading handoff expires after 120 seconds; ordinary observation gaps over four seconds clear continuity. This conservative first version may lose carried identity for unsupported skins between selection screens; it does not silently retain an old champion forever.
- No actual live LoL/Vanguard match or clean current-client transition has been verified. Independent public snapshots and original synthetic lifecycle tests are separate evidence.

## Capture consent and OS metadata

`automatic_windows.py` binds the unique verified client/game installation after Start; `session_windows.py` retains the explicit selected-window diagnostic policy. Automatic discovery checks the executable signature/product identity or asks for an explicit session-only installation confirmation when it cannot establish that identity. It pins HWND, PID, process creation time and final executable path. The client must be `LeagueClientUx.exe` or `LeagueClient.exe`. A newly created unique `Game/League of Legends.exe` under the same final installation root may be adopted only within the active session. The automatic path can connect to a pre-existing game using fresh HUD evidence; it cannot inherit a prior selection. Another installation or multiple game windows are never guessed. PID reuse/window recreation invalidate old observations and require a fresh unique binding. The older selected-client diagnostic policy still requires a newly started game for its selection handoff.

Windows process handles request only `PROCESS_QUERY_LIMITED_INFORMATION (0x1000)` for `QueryFullProcessImageNameW` and `GetProcessTimes`. Final-path resolution uses `FILE_READ_ATTRIBUTES (0x80)` to resolve junctions/reparse paths. No process-memory access right, memory reads, LCU/private client API, injection or input hooks are used. A filename is not a security certification; these checks constrain capture scope rather than certify the game executable.

The app rechecks process identity before capture and on OCR result acceptance. Handoff opt-out, Stop, target change and Close revoke the session. A second Start revokes the previous scope before validating the next. Only the current foreground target client area is captured. Normal screenshots remain in memory.

## Reproduce local checks

```sh
python -m unittest discover -s tests
python tests/native_selection_qt_validation.py
python scripts/validate_champion_select_screenshots.py --rosters /path/to/authorized-roster-cache --fixtures /path/to/authorized-fixture-manifest.json --output reports/champion-select-genuine.json
```

The Qt test uses original artwork and a fake metadata resolver, clearly labeled. The separate Windows EXE diagnostic uses original owned C# client/game fixture executables with actual paths, creation times and HWNDs, unchanged production Start/capture/handoff logic, and actual local OCR. It never launches a game, touches a user account, or changes system display/security settings. Synthetic ambiguity/scene-loss injections are explicitly identified in its report. Genuine external screenshots and Riot portraits are not redistributed.
