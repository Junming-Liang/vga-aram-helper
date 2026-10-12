# VGA乱斗助手 v0.3.0：验证状态（2026-10-12 UTC）

本文件取代 v0.2 的功能/测试总结。旧的 `unit-tests.txt`、`ui-logic-tests.txt`、`public-sample-validation.json` 是历史报告，不代表最新统计数据或当前功能。

## 已验证

- Python 单元/HTTP/数据刷新/OTA逻辑/RPC/打包约束测试通过。最近一次整套执行134项，见 `python-unit-v03.txt`（以该文件实际计数为准）。
- 18项资料库 JavaScript 逻辑测试和16项三候选状态测试通过，见 `ui-logic-v03.txt`、`choices-ui-v03.txt`。使用 DOM stub，不能当作真实浏览器渲染验证。
- 三候选测试包含不同英雄变化、源列表顺序优先于 tier/全局值、缺失配对、胜率空/零样本、陷阱冲突、重复/未知/不满三项、OCR人工确认和旧响应丢弃。
- 真实本机 HTTP `/api/compare` 使用刚经过在线刷新验证的官方缓存返回人马三项正确顺位/统计，见 `official-api-v03.json`。
- 官方公开来源端到端刷新通过：页面→配置→匿名版本RPC→五份JSON→结构验证→原子缓存，见 `data-update-live-validation.json`。这证明获取路径成功，不证明源统计为当天更新。
- 数据包395转换验证172英雄/209海克斯/180装备/21,288配对。1,582条空胜率零样本保持为空；人马缺少炼狱导管配对不补值。见 `official-snapshot-v03.json`。
- 实际 RapidOCR3.10/ONNX Runtime1.31 CPU 识别原创合成图、空白负例、重复调用和真实 localhost OCR API 成功，见 `ocr-validation.json`。模型均以本地路径加载并验证哈希，没有云端视觉API；没有进行操作系统级出站流量审计。
- 源启动器 `--self-test` 实际验证三个模型、合成中文3/3和空白0候选，见 `source-launcher-validation.json`。源运行不是 Windows EXE 运行。
- 一张经人工标注的公开静态游戏截图，在新 wiki 全209词典下，全图、实际标题行和去叠加标题裁剪均仅匹配预期三个规范化精确名称，见 `public-sample-v03.json`。旧221词典结果仅作历史补充。真实截图及词典全集未随仓库分发。
- 安装更新已启动后，即使浏览器断开响应，旧服务仍退出；有专门回归测试。单元测试不等于Windows原生替换/回滚通过。

## 仍需独立完成的验证

- Linux 环境真实 Chromium 被环境阻止创建所需 process-singleton socket（Operation not permitted）；没有绕过隔离或公开本地服务。先前浏览器运行完成零断言。`tests/browser_validation.py` 已改为新三选一流程，等待可用环境执行。
- Windows EXE 的构建、实际启动、捆绑模型OCR、三选一与浏览器渲染，以 Windows CI/实际机器报告为准；截至此文，未据此宣称Windows通过。
- 原生 Windows OTA 文件替换、重启、健康门及失败回滚仍需实际验证。
- 未实现/未验证实时游戏捕获、英雄识别、游戏内叠加层、自动选牌、所有分辨率/版本的准确率和真实对局推荐效果。

公开游戏样例只1张，不是准确率基准。官方数据源日期为2026-09-07、游戏资料版本16.17；每次启动取得成功不代表源内容最新。没有执行目标虎牙应用或私有AI服务。
