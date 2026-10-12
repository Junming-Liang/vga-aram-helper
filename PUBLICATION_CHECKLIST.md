# VGA乱斗助手：发布检查

目标公共仓库：`Junming-Liang/vga-aram-helper`。本目录为 v0.3 集成源码；完整源码发布不代表 Windows EXE、真实浏览器或 OTA 回滚已经验收。执行状态以具体提交的 CI 结果为准。

- 原创代码、原创图标与合成样例适用 MIT；第三方数据、目标程序和模型不因根许可改变授权。
- 只上传审定源码/文档/原创 fixtures/许可/测试。不上传虚拟环境、官方完整数据快照、下载的真实游戏截图、目标源码或安装包、凭据、工作区任意文件。
- EXE 构建从官方 PyPI 固定依赖，捆绑许可证和模型哈希清单。源码仓库不提交二进制依赖。
- Windows 工作流仅 `workflow_dispatch`，使用公共仓库标准 runner，`contents:read`，不能擅改成付费大 runner。
- CI artifact 不等于 GitHub Release；OTA 仅检查正式 Release。没有发布版本时更新不可用是正确结果。
- 正式 Release 前必须实际构建并运行 Windows EXE/OCR/三选一/浏览器冒烟测试；原生 OTA 替换、重启、回滚另做验证。
- 公开说明 Linux 浏览器渲染限制、样例 OCR 仅1张静态图、人工确认、源数据日期、空统计和无实时采集/游戏悬浮层等边界。

现有 source-update、HTTP、OCR、单元测试证明对应路径可运行，不能替代 Windows 验收。
