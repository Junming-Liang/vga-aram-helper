# VGA乱斗助手 Windows 便携版

## 给使用者

- 下载经过测试的 `vga-aram-helper-版本-windows-x64.exe`，放在自己有写入权限的文件夹后双击。可重命名为 `VGA-Aram-Helper.exe`。
- EXE 包含 Python 运行时、CPU ONNX Runtime、RapidOCR 和本地模型。使用者不需要安装 Python、pip、浏览器扩展或配置 API key。
- 启动后打开默认浏览器中的本机页面。后台控制台会保留；关闭此控制台或按 Ctrl+C 退出助手。页面关闭不会自动退出后台进程。
- 单文件启动会解压自带库到 Windows 临时目录，首次启动或首次 OCR 可能需要几秒。请勿以管理员身份运行，不要放在系统目录。
- 目标平台是 Windows 10/11 x64。Windows ARM64、32 位、Windows 7/8、Wine 均不在本次交付范围。标准 Windows Server 2022 CI 成功也不等同于所有个人电脑已经测试。

### 安全与局限

这是未进行 Authenticode 签名的新 EXE，Windows SmartScreen 或杀毒软件可能提示“未知发布者”。没有付费签名、微软认证或安全信誉保证。只从本仓库的已核对发布页取得文件，核对 SHA256；如被拦截，不要关闭防护或忽略安全提示，先检查来源并向维护者反馈。

SHA256 能检测下载损坏或与该发布记录不一致，不是独立代码签名。GitHub 仓库或发布账号遭入侵时，同处一地的清单也可能被改动。

截图由使用者选择并在本机 OCR，不上传到更新服务器。启动时会访问项目配置的官方数据地址检查数据，软件更新检查访问本 GitHub 仓库。没有连接游戏、读取进程、注入、自动选取、按键控制或 Vanguard 绕过。

## 更新和文件位置

- 数据缓存、更新暂存和错误日志位于 `%LOCALAPPDATA%\VGAAramHelper\`，不写入单文件临时解压目录。
- 数据下载失败时保留并标注旧缓存；没有缓存时显示不可用原因，不把虚构演示冒充真实数据。
- 软件更新由助手内更新流程检查。需维护者先发布经过测试的版本 EXE 和对应清单；首次尚无正式 Release 时，应显示暂无更新，不能声称 OTA 已经发布验证。
- 安装前显示版本和来源并由使用者确认。替换失败或新进程未通过内置模型实际 OCR 自测及 HTTP 就绪检查时，保留旧 EXE 以便回滚。正在玩游戏时可以稍后更新。
- 诊断参数：`--version`、`--self-test --report report.json`、`--licenses`、`--no-browser`。这些参数不需要另装 Python。
- `--demo` 为明确标注的原创虚构样例；不用于真实对局。`--no-updates` 仅禁用本次软件更新检查。

## 给维护者：构建和验收

源码不是最终 Windows 可执行文件，Linux 下也不能交叉构建这个 Windows 包。需要在原生 Windows x64 构建，并实际执行产物验证。

### 手动 GitHub Actions

1. 把本项目目录完整置于仓库根目录，保持仓库公开。
2. 在 Actions 选择 **Build and test Windows EXE**，手动运行指定提交。没有 push、PR 或定时自动触发。
3. 使用标准 `windows-2022` runner，最长 25 分钟，并发旧任务会取消。工作流只有仓库只读权限，无部署、发布、签名或 secrets。
4. 成功后下载 `vga-aram-helper-windows-x64-提交SHA` artifact，解压取得 EXE、SHA256SUMS、update-manifest.json 和许可文件。这里的 ZIP 是 GitHub artifact 下载封装，里面的 EXE 是独立单文件。
5. 下载 `windows-test-evidence-提交SHA` 检查 Windows 构建记录、实际 EXE OCR/HTTP 报告和可选 UI 截图。Windows 实际测试未通过时，不上传“已测试 EXE”artifact。

公共仓库使用标准 GitHub-hosted runner 的免费规则参见 [GitHub 官方计费说明](https://docs.github.com/en/billing/concepts/product-billing/github-actions)。在未来重新运行前仍应检查账户和平台政策；不要选择 larger/self-hosted/第三方付费 runner。

### 本地 Windows 维护者构建

仅维护者需要 Python 3.12 x64：运行 `scripts\build-windows.ps1`。脚本在项目内创建 `.venv-build`，从官方 PyPI 安装固定顶层版本，构建并运行 EXE 冒烟测试。完整依赖版本写入构建证据；这不是逐文件 hash 锁定的完全可复现构建。

产物为 `dist\VGA-Aram-Helper.exe`，发布候选位于 `dist\release\`。官方模型随 wheel 提供，构建前和 EXE 自测均检查精确 SHA256；缺少模型时直接失败，不在使用者电脑上临时下载模型。

### 实际 EXE 测试覆盖

- 把 EXE 单独复制到空临时目录，从子进程 PATH 移除 Python、venv 和包目录。
- 运行 EXE `--version` 和 `--licenses`。
- 运行 EXE `--self-test`，加载 3 个内置 ONNX 模型并核验 hash；原创中文合成图识别 3 个名称，空图无候选。
- 启动实际 EXE，使用随机 loopback 端口；验证 readiness、HTTP UI、安全响应头、演示 JSON 和 `/api/ocr` 的真实本地推理。
- 调用实际 EXE 的 `/api/compare`：同样三个选项切换两个演示英雄，应给出不同的英雄专属优先项。
- 可选 Playwright 打开实际 EXE 服务的网页，完成英雄 + 三项确认、切换英雄重新比较、清空新一轮，检查 JS 错误并保存截图。
- 无真实游戏、反作弊、现场屏幕捕获或真实截图准确率测试。CI 系统预装库仍可能掩盖干净系统上的 DLL 问题；发布后仍应做 Windows 10/11 干净用户环境验证。

## OTA 发布契约

版本只在 `app_version.py` 修改。一个版本对应 `v版本` tag，Release 资产名固定为：

- `vga-aram-helper-版本-windows-x64.exe`
- `update-manifest.json`
- `SHA256SUMS.txt`
- `third-party-licenses.zip`

构建脚本从实际字节生成清单的 `schema_version: 1`、`version`、`platform: windows-x64`、`url`、`sha256` 和 `size`。必须发布同一构建的 EXE 和清单，不能替换文件后继续用旧 hash。清单 URL 指向本仓库 `releases/download/v版本/…exe`，上传 CI artifact 并不会令这个 URL 生效。

工作流不会创建 Release、tag 或 Git 提交。发布是另一个明确授权步骤。未经独立 Windows 执行结果，不能把“源码测试通过”“打包脚本准备好”表述为“EXE 已验证”。

## 上游构建资料

- [PyInstaller 运行资源路径](https://pyinstaller.org/en/stable/runtime-information.html)
- [PyInstaller 官方包与原生构建限制](https://pypi.org/project/pyinstaller/6.22.3/)
- [RapidOCR 模型出处与许可](https://rapidai.github.io/RapidOCRDocs/main/en/model_licenses/)
