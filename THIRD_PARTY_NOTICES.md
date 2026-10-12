# Optional dependency notices

The delivered application source is independently written. The source archive does not contain third-party packages/model binaries. The Windows EXE build includes RapidOCR, ONNX Runtime, their local models and required runtime libraries. Maintainer build requirements come from official PyPI; their respective licenses apply. Complete license and notice texts from the build wheels are retained inside the EXE (`--licenses-file licenses.txt`) and the accompanying third-party-licenses.zip, including Python runtime terms and RapidOCR MODEL_LICENSES.md.

- RapidOCR 3.10.0: Apache-2.0. https://pypi.org/project/rapidocr/3.10.0/
- RapidOCR model attribution/licensing: https://rapidai.github.io/RapidOCRDocs/main/en/model_licenses/
- ONNX Runtime 1.31.0: MIT. https://pypi.org/project/onnxruntime/1.31.0/ and https://github.com/microsoft/onnxruntime/blob/main/LICENSE
- Playwright 1.63.0, optional developer browser tests: Apache-2.0. https://pypi.org/project/playwright/1.63.0/
- Transitive OCR dependency versions actually used in this Linux validation are recorded in reports/ocr-tested-environment.txt. This is a validation record, not a universal platform lockfile.
- Original synthetic test images were rendered using the installed Noto CJK font. No font file is bundled. Font source: https://github.com/notofonts/noto-cjk (SIL Open Font License).

Bundled RapidOCR default weights were verified locally against these reported hashes:

- PP-OCRv6_det_small.onnx: 090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f
- PP-OCRv6_rec_small.onnx: 6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884

The application disables ONNX Runtime telemetry before creating OCR sessions, verifies bundled model SHA256 and provides explicit local model paths. These controls are not a complete independent OS-level egress audit. No cloud vision API, paid inference subscription, API key or vendor helper credential is used.

Game/augment names in the synthetic OCR fixture are labels for a recognition test. The image is original and contains no gameplay screenshot, vendor art, gameplay description or performance data.

## Windows bundling tools

- PyInstaller 6.22.3: GPL-2.0-or-later with a bootloader exception permitting bundled applications under their own terms; the build preserves its supplied license/notice texts. https://pyinstaller.org/en/stable/license.html
- Windows executable contains the original VGA branding files described in assets/branding/README.md. No Riot logo or champion artwork is included by this packaging process.
- A build records every installed distribution version and available license file in dependency-inventory.json. Build-only dependencies may appear in the notice archive without being part of the runtime.

## Native QtWidgets overlay

- PySide6-Essentials and shiboken6 6.11.2, from the official Qt PyPI distributions: https://pypi.org/project/PySide6-Essentials/6.11.2/ . The applicable LGPLv3 option is selected; the application's original source remains MIT. No QtWebEngine or browser runtime is used.
- Official wheels omit full license text files. The build verifies and copies `packaging/qt-licenses/`, including full LGPLv3/GPLv3 terms and 149 verbatim upstream notice files for Qt Base (including Qt Network and its MPL-2.0 Public Suffix List/BSD lookup notices), PySide/Shiboken, SVG and image-format dependencies. `PROVENANCE.json` records exact-version official source archive hashes and each notice file hash.
- Release assets also include the four exact official Qt/PySide source archives and the same-commit application source ZIP. `source-access.json` records their hashes, sizes and source commit. Keep these assets accessible beside the binary; inspect `qt-licenses/SOURCE_AND_RELINKING.txt` for the corresponding-source and modified-library rebuild route. This file is not a blanket legal-compliance or Qt endorsement claim.
- The Windows archive inventory records included Qt DLLs/plugins. Unneeded software-OpenGL fallback, D3D compiler, Qt OpenSSL/PDF plugins and WebEngine binaries are excluded. Required Qt Network libraries and the certificate-only/Windows Schannel/network-list-manager backends are covered by the supplied Qt Base sources and notices. Any future additional library needs its own license/source review.
