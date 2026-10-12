# VGA乱斗助手 v0.3.0

独立实现的英雄海克斯三选一助手：**选择英雄 → 输入或截图识别三个候选 → 人工确认 → 查看该英雄的官方推荐顺位、评级、配对胜率、选取率和样本量。**

普通启动会检查官方公开数据，失败时保留上次验证通过的缓存。软件更新检查来自本项目 GitHub Releases，安装前需要确认。截图 OCR 使用本机 CPU 和本地模型，不需要付费 AI、账号或 API key。

## Windows 用户：运行 EXE

目标发布物为 `VGA-Aram-Helper.exe`，窗口与产品名均为 **VGA乱斗助手**。构建会捆绑 Python 运行时、RapidOCR、ONNX Runtime 和三个本地模型，用户不用安装 Python。

双击 EXE，等待首次数据检查后，默认浏览器会打开本机页面。仅监听 `127.0.0.1`，不是公开网站。关闭启动窗口可退出。

**当前源码包并不等于已经验证的 Windows 发布版。** 本轮已完成 Linux 上的真实 OCR、HTTP 和数据更新测试；只有 Windows 构建工作流成功运行、实际 EXE 冒烟测试通过后，才能声称对应 EXE 已通过 Windows 验证。见 `WINDOWS_EXECUTABLE.md`、`WINDOWS_TESTING.md` 和 `reports/VALIDATION.md`。

## 使用方法

1. 左侧搜索并选择英雄，可搜索称号和本名，例如“战争之影”“赫卡里姆”“人马”。
2. 填入这回合实际出现的三个海克斯。也可以选择已有截图，在本机 OCR 后确认名称填入三个位置。
3. 检查左、中、右三个名称及英雄，点击“确认三项，比较推荐”。
4. 查看推荐与依据。换英雄、修改任意候选或点击“换一轮”会清除旧结果，必须重新确认。

不会根据任意截图文字猜英雄；不会自动捕获游戏、注入进程、绘制游戏悬浮层或替用户点选卡片。全图 OCR 可能读到其他叠加文字，建议裁剪到卡片标题区域并核对结果。

## 推荐依据和诚实的空值

主路径使用官方公开 wiki 的 `champion-detail[].augmentRecommendations`：

- **保留官方数组顺序**，不按 tier 或全局海克斯胜率擅自重新排序。
- 每个候选展示源顺位、源 tier、该英雄与海克斯的 `winRate`、`pickRate`、`numGames`。
- 源百分比字符串按百分数解析，例如 `65.02%` 显示为 65.02%，不会误当 0.6502%。
- 任一候选缺少该英雄配对记录、胜率为空或样本缺失/为零时，显示可用源顺位，但不声称已完成可靠三项比较，也不输出唯一推荐。
- 所有三项统计可用时，优先考虑官方表顺位最高项；这仍是资料参考，不是胜负预测，也不是复现虎牙远程 AI 模型。
- 如额外导入旧版英雄联动/陷阱说明，原理由和冲突单独展示。不能因在 `specialAugments` 中就假定无条件适用；缺失关系也不代表负面。
- 海克斯全局参考胜率与英雄配对胜率分别标注。**全局值不参与本次英雄三选一排序。**
- 源统计区间、地区、置信区间和具体计算口径未提供时不推测；`pickRate` 按源含义保留，不冒充推荐分。

2026-10-12 检查到的数据包为 **395**，游戏资料版本 **16.17**，源 `date` 为 **2026-09-07**。172 位英雄、209 个海克斯、21,288 条英雄配对记录中，有 1,582 条胜率空且样本为 0。本程序保留这些空值。**每次启动获取成功，不代表来源的统计内容刚刚更新，也不保证适合当前客户端版本。** 界面分别显示来源日期与获取时间。

资料库、收藏和历史海克斯→装备关联作为辅助查阅保留在折叠区域，不代替前面的英雄三选一。

## 官方数据更新与缓存

启动时，从官方公开 wiki 页面发现数据配置，通过匿名公开版本接口取得版本与 CDN 根路径，下载五份 JSON，验证结构后原子保存。只允许已核实的官方域名，设置大小、超时和结构限制；不执行网页脚本，不调用私有识别服务，不携带凭据。

- 更新成功：使用本次验证数据。
- 更新失败但有完整缓存：继续用缓存并显示失败原因与日期。
- 首次启动没有缓存且更新失败：明确显示数据不可用，**不偷偷改为演示数据**。
- 缓存在 Windows `%LOCALAPPDATA%\VGAAramHelper\data`；开发测试可用 `VGA_STATE_DIR` 指定单独目录。
- 为最小化依赖，当前正式刷新只接新 wiki 数据；旧版联动说明需要显式本地导入，不将其伪装成新统计。

开源源码包不附带官方数据全集、虎牙客户端代码、网页脚本、安装包、人物图片、提取凭据或真实游戏截图。公开可访问不等于有权再分发；使用者应核对数据服务与游戏相关条款。来源见 `SOURCE_NOTES.md`。

## 软件更新

只检查 `Junming-Liang/vga-aram-helper` 的正式 GitHub Release。发现新版本后显示版本和说明，用户确认后才下载/安装，校验版本清单、文件长度和 SHA-256；替换/重启由独立更新进程完成，保留回滚路径。

源代码运行模式可查看更新状态，但不覆盖 Python 源文件。正式 Windows EXE 才启用应用内安装。尚未发布对应 Release 时显示无可用版本或检查失败，不能假装已升级。实际 Windows 替换、重启及回滚必须另经 Windows 测试，不能用单元测试代替。详见 `UPDATES.md`及 `WINDOWS_EXECUTABLE.md`。

## 开发者启动

普通 HTTP/三选一/数据更新只用 Python 标准库。OCR 需要 Python 3.11/3.12 和官方 PyPI 依赖；源代码启动不等于终端用户必须安装 Python。

```sh
# 联网检查官方数据，不启用 OCR
python server.py

# 明确的离线虚构演示，不能用于真实对局
python server.py --demo

# 开发环境：先在独立虚拟环境安装固定 OCR 依赖
python -m venv .venv
# Windows: .venv\Scripts\python.exe
.venv/bin/python -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-ocr.txt
.venv/bin/python launcher.py
```

访问 http://127.0.0.1:8765 ，按 Ctrl+C 退出。端口占用时可加 `--port 8767`；EXE 启动器会为默认端口冲突选空闲端口。网络检查有超时，首次加载可能需要数十秒。

显式导入旧参考数据：`python import_data.py /path/to/authorized-json private-data.json`，然后 `python server.py --data private-data.json`。这是开发/参考模式，不等于官方自动更新模式。新 wiki 原始数据可按 `wiki:{version,championDetail,championList,augmentDetail,augmentList,itemDetail}` 的对象结构显式传入，`engine.normalize` 负责净化和转换。

## 验证

```sh
python -m unittest discover -s tests -v
node --check static/app.js
node --check static/choices.js
node --check static/ocr-ui.js
node tests/test_ui_logic.js
node tests/test_choices_ui.js
# 已安装 OCR 依赖时
python tests/ocr_smoke.py
python launcher.py --self-test
```

- 三选一覆盖换英雄、源顺位、统计空值、重复/未知候选、条件、陷阱、数据失败；HTTP 路径实际运行。
- JavaScript 状态测试用 DOM stub，不能证明视觉布局或真实浏览器兼容性。
- 本地 OCR 合成图与一个公开游戏截图有限样例已实测；209 项新词典下全图、实际标题行和排除叠加文字的标题裁剪均识别出预先人工标注的三个名字。不是总体准确率基准。
- 官方网络刷新端到端测试通过；快照转换验证 172/209/180 条目录和 21,288 条配对。
- 当前 Linux 环境 Chromium 创建所需 socket 被限制，渲染测试被阻塞，未绕过隔离。
- Windows EXE、浏览器和更新回滚状态以 CI/实际测试报告为准；未运行不能写作通过。

## 许可和实现边界

原创代码、原创图标与合成测试数据适用根目录 `LICENSE`（MIT）。第三方 OCR 代码/模型有各自许可，捆绑 EXE 必须携带 `THIRD_PARTY_NOTICES.md` 与许可文件。见 `OCR_SETUP.md`。

本项目根据公开数据协议和行为证据独立实现。真实助手包含原生 Windows 采集/悬浮层和上游远程 AI 服务，不能仅靠客户端分析获得完整等价模型。本项目不执行或分发目标源码、不使用嵌入凭据、不接私有 AI 后端。`analysis/` 是经过清理的协议/行为摘要与纯虚构回放输入，仅作研究记录。
