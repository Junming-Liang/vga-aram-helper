# 发布检查表

适用于 [Junming-Liang/vga-aram-helper](https://github.com/Junming-Liang/vga-aram-helper) 的源码和 Windows 便携版发布。

## 源码

- [ ] 只包含项目源码、文档、原创图标、合成样例和许可文件。
- [ ] 未提交虚拟环境、完整第三方数据集、真实游戏截图、目标客户端、安装包或凭据。
- [ ] 本地链接有效，README 的使用方法和发布状态与当前版本一致。
- [ ] 新增依赖已列入 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 构建与测试

- [ ] `app_version.py` 版本号、目标 tag 和清单版本一致。
- [ ] 使用公开仓库的标准 Windows runner；运行前检查账户存储配额，不启用付费 larger runner。
- [ ] 记录构建的源码提交 SHA 和 Actions 链接。
- [ ] Python、JavaScript、实际 EXE OCR/HTTP/三选一及浏览器诊断、原生模拟窗口捕获/穿透/生命周期测试通过。
- [ ] Windows 10/11 用户环境测试结果和原生 OTA 验收状态已记录。
- [ ] EXE、清单、校验文件和许可包来自同一次成功构建。

## Release

- [ ] 按 [Windows 指南](WINDOWS_EXECUTABLE.md#release-文件) 上传完整发布文件。
- [ ] 从下载地址重新核对 EXE 的大小与 SHA-256，确认与 Manifest 一致。
- [ ] Release 说明列出测试环境、已知问题和未验证项目；仅在原生测试通过后标注 OTA 替换、重启、回滚已验证。
- [ ] 审核实际 Qt DLL/plugin 清单、对应源码与应用源码哈希、LGPL 修改库重建说明；源码归档随同一 Release 提供。
- [ ] 保留第三方代码及模型许可，说明 EXE 未做 Authenticode 签名。
- [ ] 更新 README 的下载入口和 [验证记录](reports/VALIDATION.md)。

CI artifact 用于构建交接，上传 artifact 不会创建 tag 或 Release。应用更新器只识别正式 GitHub Release。
