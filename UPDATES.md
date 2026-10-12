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
