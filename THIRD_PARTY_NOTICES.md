# Optional dependency notices

The delivered application source is independently written. Third-party packages/model binaries are not included in this ZIP. Installing optional requirements fetches packages from official PyPI; their respective licenses apply.

- RapidOCR 3.10.0: Apache-2.0. https://pypi.org/project/rapidocr/3.10.0/
- RapidOCR model attribution/licensing: https://rapidai.github.io/RapidOCRDocs/main/en/model_licenses/
- ONNX Runtime 1.31.0: MIT. https://pypi.org/project/onnxruntime/1.31.0/ and https://github.com/microsoft/onnxruntime/blob/main/LICENSE
- Playwright 1.63.0, optional developer browser tests: Apache-2.0. https://pypi.org/project/playwright/1.63.0/
- Transitive OCR dependency versions actually used in this Linux validation are recorded in reports/ocr-tested-environment.txt. This is a validation record, not a universal platform lockfile.
- Original synthetic test images were rendered using the installed Noto CJK font. No font file is bundled. Font source: https://github.com/notofonts/noto-cjk (SIL Open Font License).

Bundled RapidOCR default weights were verified locally against these reported hashes:

- PP-OCRv6_det_small.onnx: 090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f
- PP-OCRv6_rec_small.onnx: 6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884

The application disables ONNX Runtime telemetry before creating OCR sessions and blocks Python socket connection functions during OCR initialization/inference. These controls are not a complete independent OS-level egress audit. No cloud vision API, paid inference subscription, API key or vendor helper credential is used.

Game/augment names in the synthetic OCR fixture are labels for a recognition test. The image is original and contains no gameplay screenshot, vendor art, gameplay description or performance data.
