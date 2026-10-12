<!-- project-header:start -->
<p align="center">
  <img src="assets/branding/vga-icon-128.png" width="112" height="112" alt="VGA乱斗助手图标">
</p>
<h1 align="center">VGA乱斗助手</h1>
<p align="center"><strong>英雄专属三选一 · 本地截图识别 · 公开数据参考</strong></p>
<p align="center">
  <a href="https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/windows-build.yml"><img src="https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/windows-build.yml/badge.svg?branch=main&amp;event=workflow_dispatch" alt="Windows CI：最近一次手动构建与测试"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-16a34a" alt="License: MIT"></a>
  <a href="app_version.py"><img src="https://img.shields.io/badge/source-v0.3.0-0891b2" alt="源码版本 v0.3.0"></a>
  <a href="WINDOWS_EXECUTABLE.md"><img src="https://img.shields.io/badge/status-in%20development-d97706" alt="开发中，尚未正式发布"></a>
</p>
<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="WINDOWS_EXECUTABLE.md">Windows 指南</a> ·
  <a href="DATA.md">推荐与统计</a> ·
  <a href="CONTRIBUTING.md">参与贡献</a> ·
  <a href="https://github.com/Junming-Liang/vga-aram-helper/issues">反馈问题</a>
</p>
<!-- project-header:end -->

选好英雄，填入当前回合的三个海克斯，即可查看英雄专属推荐顺位、评级和统计数据。免费、开源，无需登录；截图识别在本机运行，不需要 AI 订阅或 API key。

CI 徽章对应最近一次手动构建与测试，不代表游戏内适配已经验收。当前尚无正式 Release。

## 功能

- **英雄专属比较**：按英雄名称或别名搜索，对比三个候选的推荐顺位、配对胜率、选取率和样本量。
- **本地截图识别**：用 RapidOCR 读取截图中的海克斯名称，核对后填入候选。
- **启动检查数据**：从虎牙官方公开 wiki 获取资料，网络不可用时使用已验证的缓存。
- **资料库与收藏**：查阅海克斯、装备和已导入的联动说明；收藏保存在当前浏览器。
- **软件更新提示**：启动器检查 GitHub Releases，新版本经确认后才下载安装。

助手通过本机浏览器使用。英雄和截图由你选择，不连接游戏进程，也不自动选牌。

## 快速开始

### Windows

Windows 便携版尚未正式发布，可在 [Releases](https://github.com/Junming-Liang/vga-aram-helper/releases) 查看发布情况，或关注 [Windows 构建](https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/windows-build.yml)。便携版的目标平台为 Windows 10/11 x64，打包包含 Python 和 OCR 模型。

目前可以从源码运行。构建方法见 [Windows 指南](WINDOWS_EXECUTABLE.md)。

### 从源码运行

安装 Python 3.11 或 3.12，下载源码后在项目目录运行：

```sh
python server.py
```

打开 <http://127.0.0.1:8765>，按 `Ctrl+C` 退出。首次获取资料可能需要数十秒；此方式支持手动输入，截图识别的依赖安装见 [OCR 指南](OCR_SETUP.md)。

只想看看界面，可以运行 `python server.py --demo`。演示模式使用虚构数据。

## 使用方法

1. 搜索并选择英雄，例如“战争之影”“赫卡里姆”或“人马”。
2. 输入三个海克斯名称，或选择截图识别。裁剪到卡片标题区域通常更便于核对。
3. 确认英雄及左、中、右三个名称，点击“确认三项，比较推荐”。
4. 换英雄或修改候选后重新比较；下一回合点击“换一轮 / 清空”。

比较结果保留来源的英雄推荐顺序，全局胜率不参与排序。缺少配对记录或有效样本时，会显示已有资料并提示信息不足。详细字段解释见 [推荐与统计说明](DATA.md)。

## 数据与隐私

数据来自[虎牙官方公开 wiki](https://gametool.huya.com/league-of-legends/wiki/index.html?embed=1)。页面会分别显示来源日期和获取时间；刚刚下载的数据也可能对应较早的游戏版本，使用前请留意版本信息。

截图只交给同机 OCR 进程处理，不保存到硬盘或上传云端。服务仅监听 `127.0.0.1`。联网请求用于检查公开数据和软件更新；软件安装需要确认，源码模式不会覆盖本地代码。更新机制见 [UPDATES.md](UPDATES.md)。

## 开发与贡献

欢迎通过 [Issues](https://github.com/Junming-Liang/vga-aram-helper/issues) 报告问题，或提交代码与文档改进。

- [开发环境与测试](CONTRIBUTING.md)
- [Windows 构建](WINDOWS_EXECUTABLE.md)与[测试指南](WINDOWS_TESTING.md)
- [数据来源](SOURCE_NOTES.md)与[验证记录](reports/VALIDATION.md)

## 许可

项目代码、图标和合成测试数据采用 [MIT License](LICENSE)。OCR 依赖与模型遵循各自许可，见[第三方声明](THIRD_PARTY_NOTICES.md)。第三方游戏数据与素材不在本项目许可范围内。

本项目为独立实现，与 Riot Games、英雄联盟及虎牙无官方关联。
