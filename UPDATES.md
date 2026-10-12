# 数据更新与 Windows 软件 OTA

## 启动行为

正常启动会重新检查两条独立更新通道：

1. **数据自动更新**：发现当前虎牙海斗 wiki 的前端入口与公开版本服务，取得完整 JSON 数据并验证后自动使用。
2. **软件检查**：读取 `Junming-Liang/vga-aram-helper` 的 GitHub 最新稳定 Release。发现新版本时只提示；用户明确确认后才下载和安装。

数据获取不需要账号、API 密钥、付费 API、浏览器登录或目标助手软件。不会读取 Cookie，不上传截图，不执行网页脚本，不修改游戏进程。

## 官方数据来源与发现方式

- 页面入口：`https://gametool.huya.com/league-of-legends/wiki/index.html?embed=1`
- 从本次页面的 `script src` 发现当前 `index-*.js`，把脚本当文本读取，提取明确的 `VITE_TOOL_ID` 字面量。
- 使用独立实现的最小 JCE/WUP 编解码器调用公开匿名 `webLiveUI.getGameToolVersion`：`https://cdnws.api.huya.com/`。请求不包含用户 UID、Cookie、令牌、设备标识或账号信息。
- 从响应中取 `version` 与 `dataBaseUrl`，验证地址后构造该版本下的 `champion-list.json`、`augment-list.json`、`champion-detail.json`、`augment-detail.json`、`item-detail.json`。
- 不把任何具体版本号、哈希 JS 文件名或 CDN 数据目录写死成“最新版本”。
- 若页面/前端包仅遇到临时 5xx 或超时，可用已独立核验的公开工具标识 `p81hl812` 继续请求实时版本服务，并记录 `discoveryMethod`。这不是固定数据版本；403 等访问拒绝不触发此备用发现方式。
- 旧攻略图鉴的发现/格式适配保留在模块内，但不会自动替代现代 wiki 的推荐数据。

只允许已验证的官方 HTTPS 域名；重定向也逐跳验证。拒绝非 HTTPS、用户凭证 URL、非标准端口、未知域名以及越界数据根目录。网页和 JavaScript 均仅作为数据解析。

### 验证与缓存

- 页面上限 2 MiB，前端包上限 8 MiB，单个数据文件上限 16 MiB，总数据上限 32 MiB。
- 单次请求超时与整次启动数据检查的 50 秒截止时间共同限制等待。
- JSON 拒绝重复字段、NaN/Infinity、过深嵌套和超长列表/文本。
- 检查英雄和强化的列表/详情 ID 集合一致、没有重复 ID、补丁一致、关系指向有效强化、百分比范围以及样本量类型。
- 只有整组数据通过后才提交；每个源文件记录 URL、字节数、SHA-256。另记录页面、前端包与版本响应哈希。
- 缓存是单个自包含 JSON 信封；临时文件写完并 fsync 后原子替换。保留 `current.json` 和 `previous.json`。
- 联网或校验失败时，重新验证最后可用缓存及其哈希；当前缓存损坏时尝试上一份。
- **首次启动无网络且无有效缓存时，显示“数据不可用”，不生成虚构推荐。**

默认存储：Windows `%LOCALAPPDATA%\VGAAramHelper\data`。测试可用 `VGA_STATE_DIR` 指定独立目录。生产 EXE 内不封装官方数据快照，以免把过期数据误称最新。

### 日期与版本的含义

`wikiDataVersion` 是数据发行版；`gamePatch` 是源 JSON 的游戏补丁字符串；`sourceDataDate` 是所有英雄详情一致声明的数据日期；`fetchedAt` 只是本机抓取时间。它们不相互替代。不擅自修改源补丁编号；源没有公布准确更新时间时 `sourceUpdatedAt` 保持空。

某强化条目 `winRate=""` 且 `numGames=0` 表示未知/没有有效样本，不是 0% 胜率。英雄推荐保留官方数组顺序，不能用总体胜率或字母等级重新排序后冒称官方名次。

## GitHub Release 发布契约

仅信任本仓库：`https://github.com/Junming-Liang/vga-aram-helper`。

Release 使用稳定标签（例如 `v0.3.1`），至少包含：

- `vga-aram-helper-0.3.1-windows-x64.exe`
- `update-manifest.json`
- 建议同时发布便于用户人工校验的 `SHA256SUMS.txt`

Manifest 示例（哈希与大小必须由实际发布的 EXE 计算）：

```json
{
  "schema_version": 1,
  "version": "0.3.1",
  "platform": "windows-x64",
  "url": "https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.3.1/vga-aram-helper-0.3.1-windows-x64.exe",
  "sha256": "实际文件的小写 SHA-256 十六进制摘要",
  "size": 12345678
}
```

软件只检查最新稳定版，不自动降级，不接受预发布版或其他仓库的 Manifest/EXE。Release API 中的资产 URL、大小必须与 Manifest 一致；如 API 提供 digest，也必须与 Manifest 一致。下载上限 512 MiB。

**当前方案没有代码签名或签名更新元数据。SHA-256 可检测损坏与不一致，不证明发布者身份，不能防御已被攻陷的 GitHub 发布账号。** 不应宣称“已签名”“绝对安全”。Windows SmartScreen 提示可能存在。

## 一体 EXE 的安装事务

支持的本机文件名为 `VGA-Aram-Helper.exe` 或 `vga-aram-helper-<version>-windows-x64.exe`。不要从需要管理员权限的目录运行；使用有写入权限的普通文件夹。

1. 用户对具体版本确认安装。
2. 下载到 `%LOCALAPPDATA%\VGAAramHelper\updates\update-<随机标识>\candidate.bin`。
3. 验证实际大小、完整 SHA-256、Windows x64 PE 标头。
4. 把**当前已安装 EXE**复制为独立 `updater.exe` 并核对哈希；不下载或执行更新脚本。
5. 启动当前 EXE 的更新模式，原助手退出。更新进程获取目标 EXE 的操作系统级互斥文件锁，再等待旧进程完全结束。同一路径同时只能有一个更新事务，锁持续覆盖就绪检查和回滚，进程崩溃时系统释放锁。
6. 在目标 EXE 同目录暂存候选文件，验证后先生成并核对 `.previous` 备份；原文件仍保持可运行。
7. 用同卷原子替换把候选文件放到目标路径。新程序通过单独的 PyInstaller extraction 生命周期启动。
8. 新程序通过内置 OCR 模型校验和实际推理自检、成功绑定本地服务器、实际 `/health` 可访问，且运行中的版本号与 Manifest 一致后，写带随机令牌的就绪标记。最长等待 150 秒。
9. 新程序崩溃或未及时就绪时，停止其进程树、原子恢复 `.previous`，用 `--no-updates` 重启原版。

正常成功后保留一份 `.previous` 备份。下一次更新成功进入替换前会刷新该备份。不会把 EXE 安装到任意 Manifest 指定的路径；Manifest 根本不提供安装目标。

如防病毒软件或目录权限阻止替换/回滚，更新结果写在对应目录的 `result.json`。保留旧 EXE/备份，用户可以退出全部助手进程后人工恢复；程序不会请求提权或关闭安全保护。断电等系统级中断不能靠进程内测试保证自动恢复，`.previous` 提供人工恢复路径。

## 集成接口

```python
result = data_updates.refresh_official_data(cache_dir)
# result = {"data": raw_dataset_or_none, "status": {...}}
# engine.normalize(result["data"]) 由应用核心处理。

status = updates.check_for_update(current_version)
# 自动检查仅获取 Release/Manifest 元数据。

plan_path = updates.prepare_update(
    status["release"], current_executable, state_dir, confirmed=True
)
updates.launch_update(plan_path)
# 当前主进程随后必须退出。

# launcher --apply-update <path>
raise SystemExit(updates.apply_update(path))

# 新程序成功响应 /health 后：
updates.mark_update_healthy(token_path)
```

`--no-updates` 适用于离线自检/回滚启动。`--demo` 必须由用户明确选择，不能成为联网失败时的自动替代品。

## 验证范围

- `python -m unittest discover -s tests -p 'test_*updates.py' -v`
- `python -m unittest discover -s tests -p 'test_huya_rpc.py' -v`
- 单测覆盖发现新哈希、主数据完整性、网络失败、无缓存、缓存损坏、回退、未知域名/重定向、确认门槛、Manifest/PE/哈希、目标未退出、原子替换准备和模拟崩溃回滚。
- 模拟 Windows 更新测试不等于真实 Windows 安装验证；最终交付须明确哪些 EXE 启动、OCR、锁文件替换和回滚项目在 Windows 实机跑过。
- 真实网络验证记录：`reports/data-update-live-validation.json`。失败结果也如实保留，不据此宣称当前已联网成功。

Windows 文件替换语义参考：[Microsoft 文件管理文档](https://learn.microsoft.com/en-us/windows/win32/fileio/moving-and-replacing-files)。本实现仅使用标准库文件复制、fsync、同卷替换与 Windows 进程等待。
