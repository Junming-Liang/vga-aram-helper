# VGA乱斗助手 · Public repository preparation

Public repository: https://github.com/Junming-Liang/vga-aram-helper

The original source package is published under MIT. GitHub CI has not yet run; Windows/browser validation is not established.

Before publishing:

- Approved: create a new public repository named `vga-aram-helper` in the verified authenticated user's personal GitHub account. Do not overwrite an existing repository.
- Approved: apply the MIT license in `LICENSE` to this original application and original synthetic fixtures. This does not grant rights to third-party data/assets/models or the original helper.
- Upload only this package's source files. Do not upload virtual environments, downloaded private reference JSON, downloaded public game screenshots, target executable/source/assets, credentials, or unreviewed workspace files.
- Keep dependency attribution in `THIRD_PARTY_NOTICES.md`. Dependencies/models are installed separately from official PyPI; none are embedded in this package.
- Keep the Windows workflow manual-dispatch-only. Public standard-runner eligibility can differ from private repository quotas; use GitHub's current billing documentation before triggering it. Do not change to a larger/paid runner.
- Retain the validation limits: actual local OCR was tested on original synthetic images and one public static screenshot with the full 221-name historical reference dictionary. Real browser/Windows/live-game validation is not established.

Source-level scans and package allowlists excluded model binaries, private datasets, target source and secrets. The public screenshot itself is not included. The full historical 221-name vocabulary was retrieved on one authorized retry and checked against the same screenshot. The source JSON remains private/local and is not bundled; report records its URL and hash. This does not establish current game-version coverage.
