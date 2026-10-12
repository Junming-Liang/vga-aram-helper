# Champion-select handoff / 选人衔接（v0.4.1）

Experimental screenshot-only selection recognition. Select the League client and explicitly Start with handoff enabled. No nickname setup or hero preselection is required. The current source is awaiting its new Windows EXE gate; v0.4.0 release evidence does not prove this feature.

## Evidence and limits

- Canonical hero text in exactly one gold-highlighted team row must agree with the central hero name. A row of small post-choice skin thumbnails is required. Two fresh observations establish a **current assignment**, never an irrevocable lock.
- Initial Champion Cards, hovered cards, bench choices and ambiguous rows do not establish assignment. Gold-row highlighting is an empirical UI anchor, not an official API contract. Unknown layouts abstain.
- Local still-image check: one July 2025 Traditional Chinese post-choice screenshot containing third-party client modifications recognized Cho’Gath; three initial-card images abstained. The three negatives represent **two distinct scenes**, with one resized/original pair. This is not current stock-client or live trade/cancel accuracy proof. [Per-case report](reports/champion-select-genuine.json).
- Selection-derived identity can show reference cards after the authorized game handoff while explicitly labeled `来自本局选人 · HUD未复核`. Matching own HUD upgrades the provenance; a conflicting HUD clears it.
- The first game-scene anchor must be a confident own-HUD match or three high-confidence exact augment titles. Once carried identity is in use, missing both anchors clears it. Loading handoff expires after 120 seconds; ordinary observation gaps over four seconds clear continuity. This conservative first version may lose carried identity for unsupported skins between selection screens; it does not silently retain an old champion forever.
- No actual live LoL/Vanguard match or clean current-client transition has been verified. Independent public snapshots and original synthetic lifecycle tests are separate evidence.

## Capture consent and OS metadata

`session_windows.py` binds the explicitly selected client’s HWND, PID, process creation time and final executable path. The client must be `LeagueClientUx.exe` or `LeagueClient.exe`. A newly created unique `Game/League of Legends.exe` under the same final installation root may be adopted only within the active session. Pre-existing games, another installation, multiple game windows, PID reuse and changed HWND identities fail closed.

Windows process handles request only `PROCESS_QUERY_LIMITED_INFORMATION (0x1000)` for `QueryFullProcessImageNameW` and `GetProcessTimes`. Final-path resolution uses `FILE_READ_ATTRIBUTES (0x80)` to resolve junctions/reparse paths. No process-memory access right, memory reads, LCU/private client API, injection or input hooks are used. A filename is not a security certification; these checks constrain capture scope rather than certify the game executable.

The app rechecks process identity before capture and on OCR result acceptance. Handoff opt-out, Stop, target change and Close revoke the session. A second Start revokes the previous scope before validating the next. Only the current foreground target client area is captured. Normal screenshots remain in memory.

## Reproduce local checks

```sh
python -m unittest discover -s tests
python tests/native_selection_qt_validation.py
python scripts/validate_champion_select_screenshots.py --rosters /path/to/authorized-roster-cache --fixtures /path/to/authorized-fixture-manifest.json --output reports/champion-select-genuine.json
```

The Qt test uses original artwork and a fake metadata resolver, clearly labeled. The separate Windows EXE diagnostic uses original owned C# client/game fixture executables with actual paths, creation times and HWNDs, unchanged production Start/capture/handoff logic, and actual local OCR. It never launches a game, touches a user account, or changes system display/security settings. Synthetic ambiguity/scene-loss injections are explicitly identified in its report. Genuine external screenshots and Riot portraits are not redistributed.
