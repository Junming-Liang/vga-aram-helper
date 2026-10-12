# v0.4.0 自动本人英雄与三候选

默认流程：确认目标窗口 → 点击开始 → 切回游戏。无需预选英雄。若检测到唯一标准 LoL 窗口会预选，仍不会擅自开始截图。

- 每次只捕获所选前台窗口的客户区；同一帧分别提供底部本人头像与中央卡牌标题区域。
- 头像只在底部、居中技能栏左侧的小区域搜索。不会读取记分板名字、队友栏头像或游戏内存，不使用 LCU、注入、输入钩子或私有 API。
- 完整 Riot Data Dragon 英雄词典的基础方形头像在本机比对：灰度相关度至少 0.88、不同英雄的次优差至少 0.07、颜色相关度至少 0.75，并排除灰度头像。数值是工程阈值，不是识别准确率。
- 英雄必须连续两帧一致。三个候选也必须分别为词典精确标题、OCR 置信度至少 0.93、三个不同的左右位置、对齐并位于牌面标题带，且连续两帧均通过。低置信帧不能算作稳定帧。
- 自动展示只复制当前英雄在公开资料里的原始 T1–T4，不展示胜率，不自行推导等级、不排序、不替玩家点击。缺失评级显示“暂无评级”。
- 新/未知英雄、候选变化、离开窗口、几何变化、截图过期或失败均隐藏旧资料。截图始终只在内存中处理；自己的叠加层必须先隐藏，即使系统截图排除功能不可用。
- 不确定时可取消自动英雄并人工纠正。进行中的手工编辑不会被后台覆盖；重新开启自动英雄可恢复自动流程。

## 支持范围和已知缺口

初版检测标准底部 HUD、客户区高度至少 600 像素、纵横比 1.55–2.45。多种分辨率通过的是原创合成测试，不是各分辨率实战认证。HUD 比例过小/过大、黑边、观战布局、死亡遮罩、特殊皮肤/变身头像与模板不一致时可能停止判断。不会为了覆盖率降低阈值或猜测英雄。

公开真实截图样本：莎弥拉（海克斯选牌）和卡特琳娜（召唤师峡谷，仅验证本人头像）正确；米利欧 ARAM 头像未匹配，记录为正例漏识别；真实死亡+记分板、观战回放、竖向裁剪三例停止判断。选牌截图上的第三方彩色文字不是识别依据；自动候选来自实际白色牌面标题。逐例 URL、哈希、结果及实现哈希保存在 `reports/hero-recognition-genuine.json`，没有打包第三方截图。

这些是少量、选择性公开截图验证，不证明所有英雄/皮肤、连续对局、Windows 采集或 Vanguard 兼容性。新 EXE 另以原创模拟窗口验证操作系统捕获、自动流程和生命周期；两类证据不得混同。

## 头像来源与缓存

官方来源：https://ddragon.leagueoflegends.com/api/versions.json 及对应 `cdn/<version>/data/en_US/champion.json`、`cdn/<version>/img/champion/*.png`。截至本次验证为 16.20.1、173 张、约 4.9 MB；与推荐资料版本分别管理。

下载只允许此 HTTPS 主机，限制字节数/图片尺寸、完整解码、SHA-256 清单、原子缓存写入。完整词典加载后才可自动识别，避免缺失竞争模板造成假高置信。每次允许更新的启动检查版本；网络不可用时使用已校验缓存并提示版本可能较旧。`--no-updates` 不下载头像。首次离线且无缓存时自动英雄不可用，仍可人工纠正。

头像仍为 Riot 所有，仅作为用户本地识别缓存，不随 MIT 源码或 EXE 分发，也不代表 Riot/腾讯授权或批准。来源介绍：https://developer.riotgames.com/docs/lol#data-dragon 。真实截图未验证再分发许可，仅在本地测试。

## Reproduce local checks

`python -m unittest discover -s tests -p 'test_*.py'`

With the existing OCR/Qt dependencies, run `tests/hero_vision_validation.py` and `tests/native_auto_qt_validation.py` (set `QT_QPA_PLATFORM=offscreen` only for non-Windows widget tests). `scripts/validate_hero_screenshots.py --help` describes the caller-provided image/portrait evaluation path. It never downloads or redistributes those test images.
