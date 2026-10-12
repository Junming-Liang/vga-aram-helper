# 本地截图识别

截图识别使用 RapidOCR 和 ONNX Runtime，在本机 CPU 上运行。它从图片中提取文字，再与当前海克斯词典匹配；无需账号、API key 或云端识别服务。

Windows 便携版的构建包含运行时、依赖和模型。以下安装步骤适用于源码运行，便携版的发布情况见 [Windows 指南](WINDOWS_EXECUTABLE.md)。

## 安装

需要 Python 3.11 或 3.12。首次安装从官方 PyPI 下载依赖及随包模型。

Windows：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-ocr.txt
.venv\Scripts\python.exe launcher.py
```

macOS / Linux：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-ocr.txt
.venv/bin/python launcher.py
```

已有 Python 3.11 环境时可替换上述版本号。启动器会打开默认浏览器；也可运行 `server.py --enable-ocr`，手动访问 <http://127.0.0.1:8765>。

## 识别截图

1. 选择英雄，在“本地截图识别”中选择已有图片。
2. 点击“识别这张截图”，核对识别出的海克斯名称。
3. 将候选填入左、中、右三个位置，确认后比较。

支持 PNG、JPEG、WebP、BMP，文件最大 8 MiB、1600 万像素。首次识别需要加载本地模型，通常比后续调用慢。

建议裁剪到三个卡片标题附近，避开聊天框和其他助手的叠加文字。小字、模糊、遮挡和 UI 缩放都可能影响结果；名称不确定时直接手动输入。

### 试用与命令行

运行 `launcher.py --demo` 后，可用随项目提供的 `fixtures/ocr-app-demo.png` 试用。它与演示词典配套，内容为虚构样例。

也可以使用本地数据文件进行命令行识别：

```sh
python local_ocr.py your-screenshot.png --data your-data.json
```

这里的 `python` 需使用已安装 OCR 依赖的解释器。输出包含识别文字、文本框、候选名称、OCR 置信度和名称相似度。

## 隐私与匹配规则

图片只在同机进程的内存中处理，不写入硬盘或上传云端。服务仅监听 `127.0.0.1`，请勿代理到公网。

模型从本地路径加载并校验 SHA-256，ONNX Runtime 遥测已关闭。公开数据更新通过独立联网流程进行；项目尚未完成操作系统级的出站流量审计。

模糊候选需要满足相似度阈值和区分度要求，低置信度或相近名称交由用户核对。OCR 不识别英雄、不定位实时游戏卡片；置信度也不代表推荐强度或游戏胜率。

## 测试与排错

```sh
python tests/ocr_smoke.py
python launcher.py --self-test
```

测试覆盖原创合成图、空白图片和本机 HTTP OCR 接口。另有一张预先人工标注的公开游戏截图测试，在数据包 395 的 209 项词典下，全图及标题裁剪均匹配到“心灵净化、暴击律动、虚幻武器”。它是有限样例，不代表整体识别准确率；原图不随仓库分发。

- [合成图测试记录](reports/ocr-validation.json)
- [公开样例与新词典测试记录](reports/public-sample-v03.json)
- [完整验证状态](reports/VALIDATION.md)

提示 OCR 不可用时，先检查是否使用了正确的虚拟环境，并确认依赖安装成功。空白结果可能来自图片质量或词典未收录；可尝试标题裁剪并检查当前数据版本。

## 依赖与许可

直接依赖固定为 RapidOCR 3.10.0 和 ONNX Runtime 1.31.0。源码不附带第三方二进制；模型出处、哈希及许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
