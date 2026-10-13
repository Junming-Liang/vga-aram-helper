"""Pinned RapidOCR 3.10.0 wheel model identities; no downloader in this module."""
import hashlib
from pathlib import Path
from ocr_privacy import disable_telemetry_before_import

EXPECTED_MODELS = {
    "PP-OCRv6_det_small.onnx": "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f",
    "PP-OCRv6_rec_small.onnx": "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
}


def verify_models(model_dir=None):
    if model_dir is None:
        disable_telemetry_before_import()
        import rapidocr
        model_dir = Path(rapidocr.__file__).resolve().parent / "models"
    output = []
    for name, expected in EXPECTED_MODELS.items():
        path = Path(model_dir) / name
        if not path.is_file():
            raise RuntimeError(f"缺少已打包的本地 OCR 模型：{name}；请重新下载完整官方发布文件。")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            raise RuntimeError(f"OCR 模型 SHA256 校验失败：{name}")
        output.append({"name": name, "size": path.stat().st_size, "sha256": digest})
    return output
