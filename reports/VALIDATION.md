# Published release verification: v0.4.5 (2026-10-13 UTC)

[Windows release run #14](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38447380079) passed every gate and published [v0.4.5](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.5) at source/tag `1939043c64554868bba3931a214d89946a339b53`. Final EXE: **106,399,997 bytes (101.47 MiB)**, SHA-256 `c43d1cd0a7848cad6c7b24ffd13943c653b823c19ed3d1992669943457ad2195`. Public asset metadata and the tested identity agree. Earlier released tags/assets remain unchanged.

- The source-only real Windows automatic-capture fixture passed all 16 required checks in 34.61 seconds, covering no-window waiting, default Start/minimization, client/game transitions, pre-existing games, process restart, same-process HWND recreation, stale-result rejection, overlay hiding, minimize/restore, foreign occlusion and cleanup. Full-client 964×602 and bounded 482×301 ROI captures reported mean-channel error 0.0 against original generated pixels.
- A 64×64 nonactivating higher window missed by the legacy nine-point test was rejected before any pixel copy. The blank HWND attempt was deliberately injected; the guarded compositor pixels were genuine OS output. Fixture publisher trust was injected only for exact freshly compiled test-owned files. Production WinVerifyTrust separately accepted an installed signed Microsoft executable and rejected unsigned and tampered copies without network retrieval.
- Seven Windows cache sharing-lock/diagnostic cases passed. These demonstrate handling and diagnostic observations under controlled file states, not the unknown owner/cause of the user's historical WinError 5. Diagnostics stay local and omit paths and pictures.
- The same packaged EXE passed 100%/150%/200% application-scale capture/overlay/OCR, selection handoff, supported image formats and same-binary native OTA success/concurrency/rollback. Same-run OpenCV parity/timing, unchanged model hashes, package size, source/license and public asset gates passed. Source fixture evidence is bound to six raw source hashes, commit and version; it is distinct from frozen-EXE evidence.
- Both Windows unit runs (official and adopted OpenCV) passed 591 tests with three skips each. Final local suite: 591 Python tests, 10 platform/dependency skips. The committed public still-image reports were actually rerun with version 0.4.5: 2/3 hero positives, 3/3 negative abstentions; 1/1 selection positive, 3/3 negatives across two distinct scenes. These are Linux official-wheel still-image results, not general game accuracy.

Real League signatures, live LoL/Vanguard compatibility, exclusive fullscreen, clean Windows 10/11 systems, mixed-monitor DPI and cross-version online updates remain unverified. No user photos or real-game screenshots were added. The historical v0.4.4 record below retains its own measurements and does not substitute for this release's evidence.

---

# Historical release verification: v0.4.4 (2026-10-13 UTC)

The [final Windows release run #10](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38417923065) succeeded in 16m09s and published
[the v0.4.4 preview](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.4) at source/tag `96245a849e16e19fec4967c9107ac393e86e5ce8`. The final EXE is
**106,343,250 bytes (101.42 MiB)**, SHA256
`e9ca12f1b2d290a7dd68fed61723772ee26f8f8ff281c76637a63e70fd88a35d`. It saves **8.765%** against v0.4.3 and **29.242%** against v0.4.2.

The newly rebuilt custom wheel/EXE passed paired output, native/format/OTA/model
and source/license gates. Final same-runner OCR median was
343.9889→373.1095 ms (**+8.47%, +29.12 ms**), within the approved >15% AND >5 ms
publication stop. Hero matching was +2.15% and capture −2.69%. These seven
samples after two warmups are measured runner results, not a no-slowdown or
real-game performance guarantee. The earlier experiment's 106,342,697-byte EXE
and +1.89% OCR change remain separate historical evidence. See
[the size record](../WINDOWS_PACKAGE_SIZE.md) and
[the recipe/evidence scope](../WINDOWS_MINIMAL_OPENCV_EXPERIMENT.md).

## Fresh limited screenshot evaluations

Both committed genuine-screenshot JSON reports were actually regenerated on
2026-10-13 with `app_version.py` set to `0.4.4`; they were not version-relabelled.
These are **Linux still-image tests using the official OpenCV wheel**, not
Windows custom-wheel evaluations. No screenshot was redistributed or fetched
anew, and no referenced third-party plugin was installed or executed.

- `hero-recognition-genuine.json`: 2/3 selected positives recognized (Samira and
  Katarina), one positive abstention (Milio), 3/3 selected negatives withheld,
  zero observed wrong heroes. The one full still-frame pipeline retained the
  three exact title matches and title-geometry pass. This does not establish
  general game accuracy or temporal/live Windows behavior.
- `champion-select-genuine.json`: the one plugin-modified July 2025 Traditional
  Chinese post-choice sample recognized; all three June 2025 prerelease
  initial-card negatives withheld. Those negatives represent two distinct
  scenes, including resized/original variants of one scene. Current unmodified
  client behavior and live trade/cancel sequences remain unverified.
- Excluding only the application version and measured per-case elapsed times,
  both new reports exactly match the previous observed results, source/image
  identities, scope limits and implementation hashes. Elapsed times are single
  local observations, not a performance comparison with the Windows experiment.

The launch environment set `ORT_DISABLE_TELEMETRY=1` **before Python started**;
the application retains its API opt-out. Python was 3.12.14 on Linux x86_64,
with official `opencv-python-headless==5.0.0.93`, `rapidocr==3.10.0`,
`onnxruntime==1.31.0`, `Pillow==12.3.0` and `numpy==2.5.4`. This is not an outbound
network audit or a claim about historical transmissions. See
[ORT's exact upstream opt-out documentation](https://github.com/microsoft/onnxruntime/blob/v1.31.0/docs/Privacy.md).

Cached-input checks compared every screenshot with its manifest and the prior
report: all six hero fixtures and four selection fixtures were unchanged. The
173-entry roster was unchanged, and every portrait matched its cached manifest
hash and size. All three models matched the pinned identities in
`model_inventory.py`:

| Input | SHA-256 |
| --- | --- |
| Hero fixture manifest | `64e3348be660a8f13668127a8372216b9ba4c7b238d07eabc7465c46c6fca3ea` |
| Selection fixture manifest | `d0ebcb81a50472386585e96a9a0b6e33a9b37718916eb2c605c7bd734f9912ff` |
| Portrait template manifest (173 entries) | `b32ca2691dad6b333c43ea14367c0d02fe30314272d0d0b28ae00fa525d927fd` |
| English roster, version 16.20.1 | `84fd12721ea0cec502d2a747aea94d8e57d4da337422d1d3ca33a7890909787f` |
| Cached reference-data input | `475846c3dc3d45403507950b81c556dc4ee60e03cf75769d27cb286fa07296ba` |
| PP-OCRv6_det_small.onnx | `090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f` |
| PP-OCRv6_rec_small.onnx | `6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884` |
| ch_ppocr_mobile_v2.0_cls_mobile.onnx | `e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c` |

Reproduction commands, with caller-supplied permitted cached inputs (the images
and complete third-party data are not part of this repository):

```sh
ORT_DISABLE_TELEMETRY=1 "$OCR_PYTHON" scripts/validate_hero_screenshots.py \
  --templates "$TEMPLATES" --fixtures "$HERO_FIXTURES/sources.json" \
  --data "$REFERENCE_DATA/current.json" --output reports/hero-recognition-genuine.json
ORT_DISABLE_TELEMETRY=1 "$OCR_PYTHON" scripts/validate_champion_select_screenshots.py \
  --rosters "$TEMPLATES" --fixtures "$SELECTION_FIXTURES/sources.json" \
  --output reports/champion-select-genuine.json
```

## 中文范围说明

v0.4.4 的两份真实截图报告已实际重新执行：英雄样本 2/3 识别、米利欧弃权，
三个负例均弃权；选人样本一个正例识别、三个负例弃权（只含两个不同负例场景）。
输入图片、资料和三份模型哈希已核对，既有判断、弃权和限制不变。执行环境是
Linux 官方 OpenCV wheel，启动前已设置遥测退出环境变量；不代表自编译 Windows
识别准确率、真实 LoL/Vanguard 或干净 Windows 机器测试通过。

最终 v0.4.4 已重新构建、通过全部门禁并发布预览版，EXE 为 106,343,250 字节。
最终同机 OCR 中位数增加 8.47%（29.12 ms），仍通过已批准发布门限；不宣称
没有减速。实验 EXE 内仍为 v0.4.3，其体积/哈希和 +1.89% OCR 不能替代最终
结果。下面的 v0.4.1/v0.3.0 记录均保留为历史，不能据其旧测试计数或
“待验证”语句判断当前状态。

---

# Historical source verification: v0.4.1 (2026-10-12 UTC)

This section and everything below it are historical, including their test counts, version-specific links and pending-feature statements. They do not describe current release readiness.

- New selection flow: actual local Qt widgets and CPU OCR on original client/card fixtures pass nine checks (`native-selection-qt.json`). OS metadata is faked in that local test; it is not Windows handoff proof.
- Literal source-tier rendering, portrait automation and existing widget regression checks remain covered in `native-qt-offscreen.json` and `native-auto-qt.json`.
- Real screenshot evidence is version/source-hash bound: `hero-recognition-genuine.json` retains two recognized positives, one abstention, three negative abstentions; `champion-select-genuine.json` has one plugin-modified client positive and three initial-card negatives representing two distinct scenes. These small samples do not establish general game accuracy.
- The new actual Windows EXE client-to-game handoff gate uses original owned fixture executables, real process metadata/capture and production handlers. Its result is pending at this source snapshot. No live LoL/Vanguard compatibility claim.

---

# VGA乱斗助手 v0.3.0：验证状态（2026-10-12 UTC）

## 原生叠加版本的当前状态

- 当前含源评级与预发布门的源码本地执行 224 项 Python 测试、34 项 JavaScript 逻辑测试通过。
- QtWidgets offscreen 实际控件验证通过 16 项，包括原始源评级、换英雄评级变化、缺失评级、人工确认、旧截图超时、关闭竞态及小屏幕控件滚动；见 `native-qt-offscreen.json`。它不验证真实 Windows HWND/GDI/穿透能力。
- 原浏览器诊断版曾在 [Windows run 38220016126](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38220016126) 完成实际 EXE 的全部七项功能检查及清理，提交 `7f4d2a64839534e464b640ea7cf6ffc5dec2b1e5`。该记录不能替代后续原生 Qt 版本的验收。
- 不含源评级的原生基线已通过 [Windows run 38226534574](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38226534574)，源码提交 `7f0ef1b74898eb10783d8d57332fe1ce1c0e2638`，EXE SHA-256 `82ff94a4909a29fa4d2a5c33a8448f9066ea2a61cdbba8114666672648d8bc30`。该次实际原生模拟窗口捕获、OCR、鼠标穿透、焦点与关闭通过；它不是新增源评级功能的验收。
- 新源评级版本需重新执行上述检查，并额外验证同牌序换英雄的原始评级、暂无评级回退及无胜率转换。专用流程校验通过后直接发布非 latest 的 prerelease，仅上传小型 Actions 证据，不重复保存大型 artifact。当前仍等待这个版本的 Windows CI 结果。
- 原生 OTA 文件替换/回滚、Windows 10/11 用户电脑与真实 LoL/Vanguard 兼容性仍未验证。

以下为较早的 v0.3.0 源码与浏览器诊断记录；其测试计数和未实现项目不代表当前原生分支的全部状态。


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
