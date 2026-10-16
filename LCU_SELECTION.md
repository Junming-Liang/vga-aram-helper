# Optional read-only League client selection

This draft adds a default-off checkbox under advanced controls. The user explicitly grants access for the current application launch; changing the checkbox stops monitoring and requires Start again. It is never saved in preferences. Stop, scope changes and expired observations hide selection information.

The enabled feature reads the verified League installation's lockfile for its temporary local session credential. It requests only these exact paths, always with GET, directly to HTTPS 127.0.0.1:

- /lol-gameflow/v1/gameflow-phase
- /lol-gameflow/v1/session
- /lol-champ-select/v1/session

There are no writes, redirects, proxies, process-memory reads, process command-line extraction, hooks, injection, account changes or persistent credentials. Tokens and raw API payloads are never returned to the UI or logger. Only own/team/bench champion IDs survive parsing. The lockfile owner executable's final path, process creation identity and lockfile contents are rechecked. Existing window identity, focus, screenshot authorization, cancellation, generation and four-second freshness checks still apply.

TLS uses the Riot root CA from https://static.developer.riotgames.com/docs/lol/riotgames.pem. Certificate and hostname validation stay enabled. Validation failure falls back to screenshot recognition; there is no insecure retry. The root is a public certificate, not a credential.

Only confirmed Mayhem queue 2400 is accepted ([official Riot queue definitions](https://static.developer.riotgames.com/docs/lol/queues.json)). Other queues and phases clear the optional snapshot. No ordinary ARAM dataset is introduced. The existing Huya public source's literal T1–T5 values are joined by canonical champion ID, without estimating missing values. Two matching fresh snapshots are required before team/bench rows display. Own assignment continues through the existing two-observation session contract. Intent/hover is not treated as assignment. Bench rows can display without asserting an own assignment.

Failure to connect uses the existing screenshot-only detector and a visible fallback status. This does not expand its supported layouts or claim initial-card recognition. The optional path still takes a permitted screenshot to preserve the existing window/focus/visibility checks, but a successful local query avoids both selection OCR passes.

## Verification limits

Pure parser/transport boundary tests and offscreen Qt fixtures use only original synthetic data. No user credential, live League client, Windows game match, Vanguard behavior, installed release or current client TLS certificate has been tested here. Native Windows packaging and real-client acceptance remain required. This is not Riot approval.

Riot's official documentation describes the League Client API as unsupported for third-party applications and asks developers to register their app and describe endpoints: https://support-developer.riotgames.com/hc/en-us/articles/22698698001939-League-of-Legends . The project owner confirmed registration on 2026-10-16. This work did not access the portal or accept terms; owner confirmation is not independent verification or Riot approval.

Architectural comparison: https://github.com/zp96-cmd/mayhem-overlay (MIT) reads localPlayerCellId, myTeam and benchChampions. This implementation is original Python code; no project source was copied. AirLibrax's unlicensed project was not copied.

## Separate current-match identity opt-in

A separate default-off checkbox describes current-player identifier and player-list access to Riot's local Game Client API. It calls only `/liveclientdata/activeplayername` and `/liveclientdata/playerlist` on verified HTTPS `127.0.0.1:2999`, without a credential. Player identifiers are used transiently to join exactly one self row and never enter diagnostic output. The canonical `rawChampionName` suffix is resolved only against the existing hash-verified full Data Dragon roster. Every result requires fresh matching game-process/window metadata before and after the bounded requests, then the normal GUI generation, scope, focus and age guards.

A fresh current-match identity can replace an uncertain/dead HUD identity; a confident conflicting HUD makes the frame unknown. This reconciliation occurs before OCR proof and the final frame result. It does not carry identity indefinitely or weaken the three-augment confirmation rules. API failure falls back to HUD and is shown in status. Either permission toggle stops monitoring, so old callbacks cannot cross a consent change.

## Installation and client-exit limits

The optional selection reader checks only a lockfile adjacent to the verified
client executable and requires its owner to be the adjacent LeagueClient.exe.
It does not search parent directories or assume the game's installation root is
the credential directory. Other client layouts are unverified and safely fall
back to screenshot recognition.

Default automatic window discovery independently verifies a game process and
can bind it when the client exits. Advanced manually selected client-follow
requires its original client process identity to remain verifiable; if that
client closes before handoff, it refuses to inherit the old authorization.
This limitation is intentional rather than a reason to weaken identity checks.
