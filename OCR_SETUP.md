# VGA乱斗助手：免费本地截图识别

这版增加了真正的 CPU 本地 OCR：用户选一张已有截图，程序识别文字，再与您当前的数据词典匹配。没有付费 AI 接口、API key、自动游戏操作、实时捕获或游戏悬浮窗。

正式 Windows EXE 会捆绑所需运行时、依赖和模型，用户不需额外安装。下面是源码开发环境的安装方式。EXE 的实际验证状态以 Windows 报告为准。

## 开发环境安装一次

普通查阅仍只需要 Python 标准库。OCR 另需 **Python 3.11 或 3.12**。依赖和模型来自官方 PyPI 轮子；首次安装需要联网下载，之后处理图片不需要云端识别服务。

Windows，在本目录终端运行：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-ocr.txt
.venv\Scripts\python.exe server.py --enable-ocr
```

macOS / Linux：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-ocr.txt
.venv/bin/python server.py --enable-ocr
```

如果已有其他受支持的 Python 3.11/3.12 命令，可以替换创建环境的命令。程序不要求管理员权限，不修改系统 Python。

然后打开 http://127.0.0.1:8765 ，在“本地截图识别”选择图片，点击识别。

- 首先用 `fixtures/ocr-app-demo.png` 验证：它是原创虚构示例图，对应显式 `--demo` 演示词典。
- 普通启动会获取官方词典；也可以显式导入有权使用的真实数据后加 `--data your-data.json --enable-ocr`。
- 演示词典只有虚构条目；真实名称不会被凭空补造。
- 上传到这个 localhost 页面只是发送给同机 Python 进程。图片保留在内存中，不保存到硬盘，不发送到任何云端识别接口。
- 不要把服务代理到公网；程序只监听 127.0.0.1，并拒绝跨站 JSON 图片请求。

也可以不用网页，直接运行：

```sh
python local_ocr.py your-screenshot.png --data your-data.json
```

上面 `python` 应当是已安装 OCR 依赖的虚拟环境解释器。输出为 JSON，包含文字、框、候选名称、OCR 置信度和名称相似度。

## 识别边界

- PNG / JPEG / WebP / BMP；最大 8 MiB、1600 万像素。图片无需发送到第三方。
- 整张图做文字检测，再进行名称匹配；模糊候选要求较高相似度与明显优势，低置信度或相近候选不猜。
- 候选始终需要手动确认，候选填入三个可编辑位置；确认英雄和三项后再比较，不替您选择游戏中的卡片。
- **OCR 置信度、名称相似度和游戏胜率是三种不同数据。** 本功能不生成玩法评级。
- 不根据任意截图文字猜英雄，继续由用户手动选择英雄。
- 小字、模糊、遮挡、动态效果、非中文语言和不同 UI 缩放还没有真实游戏验证。可以先裁剪到卡片标题区域再试。
- 首次调用会加载本地模型。程序验证全部本地模型 SHA-256、显式传入本地模型路径，并关闭 ONNX Runtime 遥测；没有集成云端视觉 API。为兼容独立的数据更新线程，不会全局替换 Python socket。未做独立的操作系统级网络抓包审计。

## 已实测，而非承诺

2026-10-12，Linux CPU：

- 原创合成图片里的“珠光护手、炼狱导管、双刀流”全部识别并匹配
- 原创空白图片返回 0 候选
- 默认演示图的三个虚构名称通过真实 localhost OCR API 识别成功
- 重复调用保持从左到右顺序，每条都要求手动确认
- 冷 / 热耗时见 `reports/ocr-validation.json`；仅是该机器、这几张合成图的记录

另补充了 1 张公开游戏截图的有限检查：人工先读出“心灵净化、暴击律动、虚幻武器”，全图与排除第三方叠加文字的标题裁剪都识别出这三个名称。原图及裁剪不随包分发；URL、哈希、裁剪坐标和结果见 `reports/public-sample-validation.json`。随后使用公开参考快照中的全部 221 个海克斯名称重跑：全图、实际标题行和去叠加文字的标题裁剪均只匹配这三个名称，全部是规范化后精确匹配，没有额外或模糊候选。词典是历史快照，不保证当前版本覆盖。

全图中某些重复名称可能来自已有助手的叠加标签；最高置信度去重并不等于可靠的游戏卡片定位。单独标题裁剪用于检查不是只读到了叠加文字。

**这些测试不是准确率基准。一张公开静态样图不能代表用户的游戏、分辨率、版本或动态效果；实时采集、Windows OCR 运行与叠加层仍未实测。**

重跑实际 OCR 冒烟测试：`python tests/ocr_smoke.py`（使用已安装依赖的环境）。普通单元测试不需要安装 OCR 包。

## 依赖与许可

直接依赖固定为 RapidOCR 3.10.0 与 ONNX Runtime 1.31.0，CPU 推理。源码包不附带第三方二进制；Windows EXE 构建时从官方 PyPI 获取并捆绑依赖/模型。源码和模型授权来源、测试模型哈希见 `THIRD_PARTY_NOTICES.md`。

## v0.3 新词典回归

改为官方数据包395的全部209个海克斯名称后，同一公开样图的全图、实际卡片标题行、去叠加标题裁剪仍仅匹配预先标注的心灵净化、暴击律动、虚幻武器，全部规范化精确匹配。结果见 `reports/public-sample-v03.json`。这只是一个静态样例，不证明实时游戏定位或总体准确率。
