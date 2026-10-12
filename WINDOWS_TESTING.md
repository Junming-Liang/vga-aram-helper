> 正式 Windows 单文件 EXE 的构建、下载和实际可执行文件测试见 [WINDOWS_EXECUTABLE.md](WINDOWS_EXECUTABLE.md)。以下内容为早期源码验证记录/开发流程，不替代 EXE 验收。

# 准备好的免费 Windows 测试方案

`.github/workflows/windows-validation.yml` 是一个**尚未发布、尚未执行**的 GitHub Actions 工作流。它只手动触发，没有 push、pull request 或定时触发；不部署、不传截图、不上传构建产物。

## 运行前需要确认

1. 用户授权将本项目文件放入一个 GitHub 仓库的根目录；不要上传自有截图、私有导入数据或虚拟环境。
2. 检查该仓库和账户的标准 Windows runner 免费资格/剩余额度。当前计划是用户自有的公开仓库，标准公开仓库 runner 的免费政策与私有仓库额度不同；发布/执行前仍按 GitHub 当前说明核对，且不使用大型付费 runner。
3. 确认上述事项后，用户在 Actions 手动触发，并勾选 `free_runner_confirmed`。

这里仅准备本地文件，没有创建仓库、推送代码或消耗 GitHub Actions 额度。

## 测试内容

- Python 3.12：标准库单元测试与 localhost HTTP 测试
- Node 22：JavaScript 语法及隔离 UI 逻辑测试
- 可选：从官方 PyPI 安装 Playwright 1.63.0，并下载它对应的 Chromium，运行真实本地网页测试
- 可选：安装已固定的本地 OCR 依赖，识别随包的原创合成图
- 超时 15 分钟，权限仅 contents:read，不使用大型/付费专用 runner 标签，不保存 artifact

浏览器脚本已去掉 Linux 专属执行路径，默认使用 Playwright 管理的 Chromium。已有浏览器时可显式使用 `--browser-executable /path/to/chromium`。截图保存默认关闭；`--screenshots` 仅在开发者明确指定时把合成页面截图保存在本地 reports 目录。

## 当前状态

Linux 下 Python/HTTP 与真实 OCR 可以运行。当前环境 Chromium 启动仍因 process-singleton 所需 socket 被拒而失败；没有绕过隔离限制。准备工作流不等于 Windows 测试已经通过，也不能验证游戏客户端、全屏叠加或反作弊兼容性。

官方文档：
- https://playwright.dev/python/docs/ci
- https://playwright.dev/python/docs/browsers
- https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-actions/about-billing-for-github-actions
