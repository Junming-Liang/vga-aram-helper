# Windows 测试

仓库提供源码验证和单文件 EXE 验收两条手动工作流。测试结果以对应提交的 Actions 日志和报告为准；已有记录见 [验证状态](reports/VALIDATION.md)。

## 单文件 EXE 验收

在 [Build and test Windows EXE](https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/windows-build.yml) 中选择目标提交，保留 `run_browser_test` 以运行浏览器检查。

工作流使用标准 `windows-2022` runner 和 Python 3.12 x64，先运行 Python/JavaScript 测试，再构建并执行 EXE：

- 将 EXE 复制到空临时目录，从子进程 PATH 移除 Python、虚拟环境和包目录。
- 通过输出文件检查版本、完整许可和 `--self-test`；窗口化程序不依赖控制台输出。
- 核验三个内置模型的哈希，使用检测与识别模型执行实际 OCR；识别原创中文合成图，检查空图无候选。
- 启动实际 EXE，验证本机 HTTP、响应头、演示数据和 `/api/ocr`。
- 切换两个演示英雄，检查 `/api/compare` 返回对应的不同优先项。
- 使用 Playwright 操作确认、换英雄和清空流程，记录页面错误并保存合成页面截图。

随后强制运行 `tests/windows_native_smoke.py`，使用同一 EXE 的真实 Windows Qt 平台：

- 创建原生控制窗口、原创模拟游戏窗口与透明叠加窗口。
- 只捕获所选模拟窗口客户区，实际 OCR 必须识别出三个指定合成候选。
- 检查 Win32 分层/非激活/鼠标穿透样式，系统点命中须穿过叠加层落在模拟窗口。
- 检查焦点不被抢走、全局热键注册、鼠标穿透开关、旧状态失效和关闭后释放资源。
- 保存仅由本程序的模拟窗口和叠加窗口组成的 PNG；OS 截图捕获/OCR 另有独立断言。
- `windows-native-smoke.json` 记录被测 EXE 哈希，`windows-native-overlay.json` 记录原生检查；非 Windows/offscreen 后端不能通过。

全部检查通过后，工作流上传 EXE、清单、校验文件和许可文件。失败时仅上传可用的测试证据。Artifact 保留一天，需及时下载；具体命名见 [Windows 构建指南](WINDOWS_EXECUTABLE.md)。

## 源码验证

[Manual Windows validation](https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/windows-validation.yml) 适合只检查源码、不打包 EXE 的改动：

- Python 3.12 标准库单元与 HTTP 测试
- Node.js 22 语法与隔离 UI 逻辑测试
- 可选 Playwright 浏览器测试
- 可选本地 OCR 合成图测试

运行前确认标准 runner 和账户配额，勾选 `free_runner_confirmed`。此工作流不上传 artifact，报告在运行日志中查看。

本地测试命令见 [贡献指南](CONTRIBUTING.md#测试)。浏览器脚本默认使用 Playwright 管理的 Chromium；可用 `--browser-executable /path/to/chromium` 指定已有浏览器。

## 发布前的补充验证

CI 的 Windows Server 环境不能覆盖所有个人电脑。正式发布前还应在 Windows 10/11 x64 用户环境检查首次启动、原生窗口/叠加层、不同 DPI/显示器坐标、OCR 和退出流程。

应用内更新需要单独在原生 Windows 环境验收：

1. 发现新版本，取消安装后保持原版运行。
2. 确认安装，完成下载与校验、旧进程退出、文件替换和新版本启动。
3. 检查新版本 OCR 自检、真实 Windows Qt 平台、原生控制窗口与叠加样式健康门和版本号。
4. 模拟候选启动失败，检查进程清理、原版恢复和重启。
5. 检查重复安装、目标占用及目录不可写时的提示与恢复路径。

单元测试中的模拟替换与回滚不代表以上原生流程已通过。更新事务详见 [UPDATES.md](UPDATES.md)。

模拟窗口测试只验证打包与普通系统窗口行为，不涵盖真实对局、游戏窗口的实际可捕获性、独占全屏、Riot/Vanguard 兼容性或 OCR 总体准确率。通过虚拟机 CI 不能证明任何反作弊系统允许本工具。

## 参考

- [Playwright CI 指南](https://playwright.dev/python/docs/ci)
- [Playwright 浏览器管理](https://playwright.dev/python/docs/browsers)
- [GitHub Actions 计费](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
