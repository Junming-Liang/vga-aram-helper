# 参与贡献

欢迎修复问题、改进识别与界面，或完善文档。较大的功能变更建议先开 Issue 讨论，避免重复工作。

## 报告问题

请在 [Issues](https://github.com/Junming-Liang/vga-aram-helper/issues) 中提供：

- 程序版本、操作系统，以及源码运行或 EXE 运行方式
- 复现步骤、预期结果和实际结果
- 涉及推荐时的英雄、三个候选、数据版本和来源日期
- 相关错误信息；截图请先遮去个人信息

启动错误日志位于 `%LOCALAPPDATA%\VGAAramHelper\logs\last-launch-error.txt`。请只附相关片段，不要上传凭据、完整私有数据或无权公开的截图。

## 开发环境

使用 Python 3.11/3.12；Windows 构建使用 Python 3.12 x64。JavaScript 检查使用 Node.js 22。

```sh
git clone https://github.com/Junming-Liang/vga-aram-helper.git
cd vga-aram-helper
python -m venv .venv
```

以下命令中的 `python` 应指向虚拟环境解释器。Windows 为 `.venv\Scripts\python.exe`，macOS/Linux 为 `.venv/bin/python`。

手动输入、HTTP 服务和数据更新仅需 Python 标准库：

```sh
python server.py
```

使用虚构数据进行离线界面开发：

```sh
python server.py --demo
```

默认地址为 <http://127.0.0.1:8765>。端口被占用时可使用 `--port 8767`。

### OCR 与启动器

```sh
python -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-ocr.txt
python launcher.py
```

`launcher.py` 启用 OCR，检查软件更新并打开默认浏览器。源码模式仅显示更新状态，不安装 EXE 或覆盖源码。更多用法见 [OCR 指南](OCR_SETUP.md)。

### 导入本地数据

```sh
python import_data.py /path/to/authorized-json private-data.json
python server.py --data private-data.json
```

`--data` 适用于开发和旧参考资料。请确认自己有权使用导入的数据，不要提交到仓库。

新 wiki 原始数据可按 `wiki:{version,championDetail,championList,augmentDetail,augmentList,itemDetail}` 结构传入，由 `engine.normalize` 归一化并净化文本。自动更新路径的完整结构校验由 `data_updates.validate_dataset` 和 `data_updates.validate_wiki` 负责。完整来源与字段说明见 [SOURCE_NOTES.md](SOURCE_NOTES.md) 和 [DATA.md](DATA.md)。

开发时可用 `VGA_STATE_DIR` 指定独立缓存目录，避免影响日常使用的数据。

## 测试

在项目根目录运行：

```sh
python -m unittest discover -s tests -v
node --check static/app.js
node --check static/choices.js
node --check static/ocr-ui.js
node tests/test_ui_logic.js
node tests/test_choices_ui.js
```

已安装 OCR 依赖时：

```sh
python tests/ocr_smoke.py
python launcher.py --self-test
```

可选浏览器测试：

```sh
python -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-browser.txt
python -m playwright install chromium
python tests/browser_validation.py
```

浏览器测试使用本机服务和合成数据；加 `--screenshots` 可保存页面截图。Windows EXE 验收与 OTA 测试见 [WINDOWS_TESTING.md](WINDOWS_TESTING.md)。已有测试结果见 [验证记录](reports/VALIDATION.md)。

## 提交改动

- 每个 PR 聚焦一个问题，说明复现方式、改动及实际运行的测试。
- 推荐逻辑的变更应覆盖源顺位、缺失统计、重复候选和切换英雄等情况。
- 保留截图人工确认、启动数据检查和软件更新确认流程。
- OCR 保持本机推理，不引入付费服务、账号或 API key 依赖。
- 测试使用原创合成样例。仓库不收录完整第三方数据集、真实游戏截图、目标客户端源码或凭据。
- 新增依赖时同步维护[第三方声明](THIRD_PARTY_NOTICES.md)。

发布准备见 [发布检查表](PUBLICATION_CHECKLIST.md)。
