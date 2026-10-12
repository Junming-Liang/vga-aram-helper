# 数据与软件更新

启动器分别检查数据和软件版本：数据通过校验后自动使用；软件新版本先提示，确认后才下载和安装。

`server.py` 负责本地服务与数据刷新；`launcher.py` 默认打开 QtWidgets 原生控制窗口，启用 OCR 与软件更新检查；HTTP 服务仅供显式 `--headless` 诊断。源码模式只查看软件更新状态，应用内安装仅适用于 Windows EXE。

## 数据更新

### 来源发现

1. 读取[虎牙公开 wiki 页面](https://gametool.huya.com/league-of-legends/wiki/index.html?embed=1)。
2. 从页面的 `script src` 找到当前 `index-*.js`，按文本提取 `VITE_TOOL_ID` 字面量。
3. 使用独立实现的 JCE/WUP 编解码器，通过 `https://cdnws.api.huya.com/` 调用匿名 `webLiveUI.getGameToolVersion`。
4. 校验返回的 `version`、`dataBaseUrl`，下载该版本的英雄列表、英雄详情、海克斯列表、海克斯详情和装备详情。

请求不携带用户 UID、Cookie、令牌、设备标识或账号信息，网页脚本不会被执行。数据版本、前端文件哈希和 CDN 目录均在运行时发现。

页面或前端包遇到临时 5xx、超时时，可使用已核验的公开工具标识 `p81hl812` 请求实时版本服务，并记录 `discoveryMethod`。403 等访问拒绝不触发此备用方式。旧图鉴适配保留在模块内，不自动替代新版 wiki 数据。

### 验证与缓存

网络请求仅允许已验证的官方 HTTPS 域名，重定向逐跳校验；拒绝含凭据的 URL、非标准端口和越界数据目录。

- 页面上限 2 MiB，前端包上限 8 MiB，单个数据文件上限 16 MiB，整组上限 32 MiB。
- 除单次请求超时外，整次启动数据检查限制为 50 秒。
- JSON 拒绝重复字段、NaN/Infinity、过深嵌套和超长列表或文本。
- 检查列表与详情 ID 一致性、重复 ID、补丁版本、关系引用、百分比范围和样本量类型。
- 整组通过后记录各文件的 URL、大小和 SHA-256，同时记录页面、前端包与版本响应哈希。

缓存以单个 JSON 文件保存，写入临时文件并 `fsync` 后原子替换，保留 `current.json` 和 `previous.json`。联网失败时重新校验本地缓存；当前文件损坏则尝试上一份。没有有效缓存时显示数据不可用，演示模式仅由显式 `--demo` 启用。

Windows 默认路径为 `%LOCALAPPDATA%\VGAAramHelper\data`，开发测试可用 `VGA_STATE_DIR` 指定独立目录。EXE 不内置官方数据快照。

数据日期、获取时间和空值的含义见 [DATA.md](DATA.md)。

## 软件版本检查

更新源固定为 [Junming-Liang/vga-aram-helper](https://github.com/Junming-Liang/vga-aram-helper) 的正式 GitHub Release。程序不接受其他仓库的 Manifest 或 EXE，不自动降级，也不使用预发布版。

每个 Release 至少提供对应的 Windows x64 EXE 和 `update-manifest.json`，完整发布文件见 [Windows 指南](WINDOWS_EXECUTABLE.md#release-文件)。清单示例：

```json
{
  "schema_version": 1,
  "version": "0.3.1",
  "platform": "windows-x64",
  "url": "https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.3.1/vga-aram-helper-0.3.1-windows-x64.exe",
  "sha256": "实际 EXE 的小写 SHA-256 摘要",
  "size": 12345678
}
```

示例中的大小与哈希需用实际文件生成。Release API 返回的资产 URL、大小必须与清单一致；如果 API 提供 digest，也一并比对。下载上限为 512 MiB。

当前 EXE 与更新元数据未做代码签名。SHA-256 用于检查完整性，不能独立证明发布者身份；GitHub 发布账号受损也可能影响更新源。

## Windows 安装事务

支持的目标文件名为 `VGA-Aram-Helper.exe` 或 `vga-aram-helper-<version>-windows-x64.exe`，所在目录需要当前用户的写入权限。

1. 用户确认安装指定版本。
2. 下载到 `%LOCALAPPDATA%\VGAAramHelper\updates\update-<随机标识>\candidate.bin`。
3. 核对实际大小、完整 SHA-256 和 Windows x64 PE 标头。
4. 将当前 EXE 复制为独立的 `updater.exe`，核对哈希后以更新模式启动，原助手退出。
5. 更新进程持有目标文件的操作系统级互斥锁，等待旧进程完全结束。同一路径只允许一个更新事务。
6. 在目标目录暂存候选文件并再次校验，生成 `.previous` 备份，然后执行同卷原子替换。
7. 新程序使用独立的 PyInstaller 解压生命周期启动，并运行 OCR 模型校验、实际推理自检、真实 Windows Qt 平台/控制窗口及叠加样式健康检查。
8. 运行版本与 Manifest 一致且检查通过后，写入带随机令牌的就绪标记；最长等待 150 秒。
9. 若新程序崩溃或未及时就绪，停止其进程树、恢复 `.previous`，并用 `--no-updates` 重启原版。

锁覆盖就绪检查和回滚，进程崩溃时由操作系统释放。成功后保留一份 `.previous`；下次更新进入替换阶段前刷新备份。安装目录由当前 EXE 决定，Manifest 不指定安装目标。

### 失败恢复

更新结果写入该事务目录的 `result.json`。权限或安全软件可能阻止替换及回滚；遇到此类情况，请退出全部助手进程，检查日志并保留原 EXE 和 `.previous` 备份。程序不会请求提权或关闭安全防护。

断电等系统级中断可能需要人工恢复。原生 Windows 更新测试的项目与状态见 [WINDOWS_TESTING.md](WINDOWS_TESTING.md) 和[验证记录](reports/VALIDATION.md)。

## 开发接口

```python
result = data_updates.refresh_official_data(cache_dir)
# 返回 {"data": raw_dataset_or_none, "status": {...}}
# 数据由 engine.normalize(result["data"]) 转换。

status = updates.check_for_update(current_version)
# 仅获取 Release / Manifest 元数据。

plan_path = updates.prepare_update(
    status["release"], current_executable, state_dir, confirmed=True
)
updates.launch_update(plan_path)
# 当前主进程随后退出。

# launcher --apply-update <path>
raise SystemExit(updates.apply_update(path))

# 新程序通过 OCR 自检及原生窗口就绪检查后：
updates.mark_update_healthy(token_path)
```

更新相关单元测试：

```sh
python -m unittest discover -s tests -p 'test_*updates.py' -v
python -m unittest discover -s tests -p 'test_huya_rpc.py' -v
```

覆盖来源发现、数据完整性、缓存回退、域名与重定向、安装确认、Manifest/PE/哈希验证及模拟失败恢复。真实网络刷新记录见 [data-update-live-validation.json](reports/data-update-live-validation.json)。

Windows 文件替换语义参考 [Microsoft 文件管理文档](https://learn.microsoft.com/en-us/windows/win32/fileio/moving-and-replacing-files)。

## 预览版与稳定更新

GitHub 标记为 prerelease 的原生预览版不会由稳定 `/releases/latest` 检查自动推送。预览版需从其发布页手动下载。是否采用与未来正式版相同的版本 tag，不改变这一隔离；后续稳定发布应使用新的版本号，现有发布文件不由自动流程覆盖。

当前 `v0.3.0` 为预发布版。如果尚无正式稳定 Release，版本检查可能显示暂时无法取得稳定更新；这不会把预发布版提升为稳定版。将来发布更高版本的正式 Release 后，现有版本才会按上述确认与校验流程提示更新。

## 原生事务专项验证

手动工作流 `Test native Windows OTA transactions` 使用已发布 `v0.3.0` 的固定 SHA-256/大小，从正式 Release 资产取得同一 EXE。只读任务不创建新版本，不覆盖 Release，不上传大型 EXE artifact；小型测试报告受存储预算约束并保留一天。

测试将本地合成的更新计划交给真实 EXE 的 `--apply-update` 入口，检查旧原生窗口退出前的等待、同目标并发锁、同版本文件替换、备份、真实 Qt/OCR 就绪与版本标记，以及故意不匹配的预期版本触发回滚、原版重启和清理。运行进程使用隔离目录与仅对测试子进程生效的拒绝代理，不改系统网络设置、生产域名列表或应用代码。

这明确是**同一个二进制的安装事务测试**。它不能证明两个不同版本之间的升级、应用内确认按钮到下载/启动更新的完整交接、稳定 `/releases/latest` 元数据获取或断电恢复。

2026-10-12 的[Windows 专项运行 #2](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38239627458)已通过：测试源码提交 `cc88873`，使用发布源码提交 `1ce516e` 构建的原始 `v0.3.0` EXE。成功事务验证了旧窗口存活期间等待且不改目标、并发更新器被锁拒绝、文件确实替换、Qt/OCR 健康令牌与版本一致，以及完整进程退出。回滚事务将预期版本设为 `0.3.1`、保持候选真实版本 `0.3.0`，确认健康检查拒绝候选，更新器从 `.previous` 恢复原始 SHA-256 并重启原窗口。两项均通过，报告 `all_owned_processes_exited=true`。

结果见该次运行摘要中的 `windows-ota-smoke.json`。这些结论仅覆盖上述同二进制本地事务，不扩展为不同版本升级、在线获取或应用内 `launch_update()` 交接已通过。
