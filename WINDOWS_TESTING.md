# Windows 测试

仓库提供源码验证和单文件 EXE 验收两条手动工作流。测试结果以对应提交的 Actions 日志和报告为准；已有记录见 [验证状态](reports/VALIDATION.md)。

## 单文件 EXE 验收

在 [Build and test Windows EXE](https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/windows-build.yml) 中选择目标提交，保留 `run_browser_test` 以运行浏览器检查。

工作流使用标准 `windows-2022` runner 和 Python 3.12 x64，先运行 Python/JavaScript 测试，再构建并执行 EXE：

- 将 EXE 复制到空临时目录，从子进程 PATH 移除 Python、虚拟环境和包目录。
- 检查 `--version`、`--licenses` 和 `--self-test`。
- 核验三个内置模型的哈希，使用检测与识别模型执行实际 OCR；识别原创中文合成图，检查空图无候选。
- 启动实际 EXE，验证本机 HTTP、响应头、演示数据和 `/api/ocr`。
- 切换两个演示英雄，检查 `/api/compare` 返回对应的不同优先项。
- 使用 Playwright 操作确认、换英雄和清空流程，记录页面错误并保存合成页面截图。

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

CI 的 Windows Server 环境不能覆盖所有个人电脑。正式发布前还应在 Windows 10/11 x64 用户环境检查首次启动、默认浏览器打开、OCR 和退出流程。

应用内更新需要单独在原生 Windows 环境验收：

1. 发现新版本，取消安装后保持原版运行。
2. 确认安装，完成下载与校验、旧进程退出、文件替换和新版本启动。
3. 检查新版本 OCR 自检、HTTP 健康检查和版本号。
4. 模拟候选启动失败，检查进程清理、原版恢复和重启。
5. 检查重复安装、目标占用及目录不可写时的提示与恢复路径。

单元测试中的模拟替换与回滚不代表以上原生流程已通过。更新事务详见 [UPDATES.md](UPDATES.md)。

这些测试也不涵盖真实对局效果、实时截图采集、游戏叠加层、反作弊兼容性或 OCR 总体准确率。

## 参考

- [Playwright CI 指南](https://playwright.dev/python/docs/ci)
- [Playwright 浏览器管理](https://playwright.dev/python/docs/browsers)
- [GitHub Actions 计费](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
