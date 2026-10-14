# Windows 测试

## v0.4.6 新增发布门禁

- `python tests/windows_wgc_capture.py --reports reports`：真实 Windows 源码、100%/150%/200% 应用缩放，必须使用 WGC，不能以 GDI 或 offscreen 通过。
- `python tests/windows_wgc_capture.py --exe dist/VGA-Aram-Helper.exe --reports reports`：同一最终 EXE、同辅助程序哈希复验。
- 原有三档 frozen 原生叠加检查新增两次独立 OCR 后才复用、复用不增加确认帧数、实际 Qt 捕获工作线程与处理期间自己的叠加隐藏。
- 发布校验绑定完整源文件、编译配方、辅助程序清单、最终 EXE 和三档结果；缺失、不支持、回退、失败或来源不符均不能发布。

这些是门禁定义。实际通过与否需看对应 Actions 证据，不代表已验证真实游戏。详见 [参考项目优化说明](REFERENCE_OPTIMIZATION.md)。


仓库提供源码验证和单文件 EXE 验收两条手动工作流。测试结果以对应提交的 Actions 日志和报告为准；已有记录见 [验证状态](reports/VALIDATION.md)。

另有手动只读工作流 `Test native Windows OTA transactions`，复用固定 SHA-256 的已发布 EXE，专门测试同版本原生更新事务、并发互斥和版本不符回滚。它不重新发布软件，也不上传大型二进制产物。范围与尚未覆盖的两版本升级/完整下载交接见 [更新说明](UPDATES.md#原生事务专项验证)；实际结果以该次运行报告为准。

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
- 原生标签必须原样显示当前英雄的合成源评级；同样三张牌换英雄会变为另一组评级，空值/未知值显示“暂无评级”，牌序不变且没有胜率/唯一最佳输出。
- 保存仅由本程序的模拟窗口和叠加窗口组成的 PNG；OS 截图捕获/OCR 另有独立断言。
- `windows-native-smoke.json` 记录被测 EXE 哈希，`windows-native-overlay.json` 记录原生检查；非 Windows/offscreen 后端不能通过。

普通构建在全部检查通过后上传 EXE、清单、校验文件和许可文件。专用预览发布工作流则在同一任务最后一步直接发布经校验的 prerelease，不额外上传大型 Actions artifact；只保留预算允许的小型证据。失败时仅上传可用的测试证据。Artifact 保留一天，需及时下载；具体命名见 [Windows 构建指南](WINDOWS_EXECUTABLE.md)。

## v0.4.3 包体积与更新验证

[v0.4.3 发布运行 #9](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38383752875)（源码/标签 `67361ca90124a8e5dee69d1fa0c560711fe9dac6`）已通过全部门禁，最终 EXE 实测 116,559,213 字节，比 v0.4.2 减少 22.445%。实际 EXE 的 PNG/JPEG/WebP/BMP OCR 测试均识别出三个演示名称；三份 OCR 模型保持原 SHA-256。

同一新版本 EXE 通过本地原生 OTA 成功事务、并发互斥、预期版本不符回滚和全部所属进程退出检查。这是同二进制合成计划测试，不证明真实跨版本升级、在线 GitHub 下载或应用内确认交接。

发布流程重新读取并核对实际 EXE 的归档/模型/大小/哈希，还通过原生多倍率、选人衔接、源码/许可证与远端资产摘要检查。v0.4.2 文件保持不变。早期候选与最终发布大小/哈希不同，详见 [包体积记录](WINDOWS_PACKAGE_SIZE.md)。

## v0.4.2 缩放验证

[发布测试第 8 次运行](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38281910029)对应提交 `151bb0a5d0a73946bad5e603c8f07373ed19248e`。同一个 EXE 在 `QT_SCALE_FACTOR=1/1.5/2` 下分别完成原生捕获、OCR、自动英雄、三个资料卡布局、状态失效与关闭检查。每次使用固定 960×600 物理像素的原创模拟窗口，位于 1024×728 像素工作区内，叠加层严格位于其客户区内。

同次构建另运行五档进程缩放的源码矩阵，共 35 个窗口用例，覆盖重复定位、窗口平移、紧凑布局、过小窗口隐藏与恢复。非整数逻辑位移允许至多一个物理像素的坐标舍入；尺寸、重复定位和边界检查保持严格。该矩阵的实现文件哈希与同版源码 ZIP 一致。

这些检查未更改 Windows 显示设置，不能证明真实多显示器 DPI、完整可见的 4K 布局、实战 OCR 或视觉字体质量。用户报告的具体尺寸错误尚未复现到其原始配置。

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

## v0.4.5 自动发现/捕获回归

`python tests/native_discovery_qt_validation.py` 在 Qt offscreen 控件上验证默认不选窗口的 Start、后启动客户端、已有游戏、PID/HWND 替换、停止后的旧回调和会话内目录确认。这里的系统元数据和签名接受为合成替身，不是 Windows 证据。

`python tests/windows_automatic_capture.py --reports reports` 在真实 Windows 上编译并管理原创 Win32 窗口，使用实际路径/PID 创建时间和 OS 像素，默认 Start 不指定 HWND。仅该源码测试注入“本次临时目录内的原创可执行文件”发行商验证器；普通程序没有测试豁免。报告单独标记信任替身。原生 WinVerifyTrust 另以已签名系统文件、未签名原创文件及篡改副本测试。

`python -m unittest discover -s tests -p test_portrait_cache.py -v` 在 Windows 上必须实际运行文件共享锁用例；Linux 跳过不能算通过这些用例。

[v0.4.5 发布运行 #14](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38447380079)已通过该源码自动发现测试：全部生命周期/遮挡/清理检查通过，所有捕获与原创测试图的平均通道误差为 0.0；六份源码哈希与发布源码 ZIP 相同。同次运行七项原生头像缓存共享锁/诊断测试通过，最终 EXE 的多倍率、OCR、选人、更新、源码与许可门禁通过。源码测试与最终 EXE 证据分别记录；无真实 LoL/Vanguard 兼容性结论。没有用户照片或真实对局截图被加入仓库/测试报告。
