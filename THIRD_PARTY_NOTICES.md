# Optional dependency notices

The delivered application source is independently written. The source archive does not contain third-party packages/model binaries. The Windows EXE build includes RapidOCR, ONNX Runtime, their local models and required runtime libraries. Ordinary source/runtime diagnostics install the pinned official PyPI wheels. The adopted v0.4.4 Windows release instead builds its OpenCV wheel from the hash-pinned official PyPI source distribution with the reviewed downstream recipe; the other pinned runtime dependencies retain their existing sources and licenses. Complete license and notice texts from the build wheels are retained inside the EXE (`--licenses-file licenses.txt`) and the accompanying third-party-licenses.zip, including Python runtime terms and RapidOCR MODEL_LICENSES.md.

The adopted `VGA_RELEASE_PACKAGE_PROFILE=minimal-opencv-v1` uses truthful downstream OpenCV distribution metadata `5.0.0.93+vga1` (native version `5.0.0`), not the official PyPI binary. Its source, patch, Community compiler settings, compiled identity and full supplemental license/notice inventory are recorded in build provenance. The EXE and downloadable `third-party-licenses.zip` retain the verified `opencv-minimal/` notices and provenance, including the retained codec, IPP and font notices. The same-commit application source includes the exact recipe and patches; the publisher verifies their binding to paired official/custom evidence. Maintaining that source-build recipe adds ongoing work. See [the recipe and evidence scope](WINDOWS_MINIMAL_OPENCV_EXPERIMENT.md). The [final v0.4.4 release run](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38417923065) passed; this adoption does not alter the original offline models or the Qt/CRT terms and corresponding-source/rebuild rights below.

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

## Microsoft Windows runtime components

The five Microsoft Visual C++ CRT DLLs named in `microsoft-runtime/MICROSOFT_RUNTIME_NOTICE.txt` are proprietary Microsoft components, separate from Qt LGPL and the MIT application. Review and agree to their complete Microsoft end-user terms before using those components. The EXE license directory and same-release `third-party-licenses.zip` preserve the full runtime terms, scope notice, Community agreement and build-specific provenance. These conditions do not restrict the separately licensed application's source or LGPL modification/relinking rights.

The redistribution basis is a validly licensed, actually installed and used Visual Studio Community 2022 product and its Section 4 distributable-code provisions; the runtime consumer terms do not themselves grant redistribution. For the separately distributed DLLs, the build uses the exact five release CRT files from that installation, verifies valid Microsoft signatures and x64 dependencies with its tools, and preserves their unchanged bytes at every matching root/PySide archive path. Debug or unknown CRT variants and unused TUIO network input are rejected. The actual Windows Python `LICENSE.txt` is also preserved separately, including any Python-specific Microsoft runtime conditions.

The custom `cv2.pyd` uses `/MT` and embeds Microsoft release CRT object code in addition to the five separately distributed DLLs described above. That object code remains subject to applicable Microsoft terms, separately from OpenCV and Qt licenses. Microsoft's [static-linking deployment guidance](https://learn.microsoft.com/en-us/cpp/windows/deployment-in-visual-cpp?view=msvc-170#static-linking) explains that servicing statically linked libraries requires rebuilding and redeploying; [Visual Studio licensing guidance](https://www.microsoft.com/licensing/guidance/Visual-Studio) describes distribution of eligible linked library object code. The existing DLL terms and LGPL rebuild rights remain unchanged. This is a technical scope clarification, not a legal certification; the applicable agreements govern.

Official agreements and redistributable list: https://visualstudio.microsoft.com/license-terms/vs2022-ga-community/ , https://visualstudio.microsoft.com/license-terms/vs2022-cruntime/ , https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution .
