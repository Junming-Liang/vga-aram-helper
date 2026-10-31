# 本地离线模式（26.21）

目标：不访问互联网，也能显示三个候选的本地档位/热度、装备参考与装备价值差。

## 运行

```bat
:: Windows 10/11 x64 + Python 3.12 x64；依赖只需首次安装
python -m venv .venv
.venv\Scripts\python -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-build.txt
.venv\Scripts\python launcher.py
```

只要程序目录或 EXE 同目录存在 `offline/offline-data.json`，启动器会**默认使用离线包**并禁用联网；
需要临时联网数据时加 `--online`。也可以用 `--offline` 显式启用（额外允许状态目录中的包），
或用 `--offline-data PATH` 指定路径。`--demo` 不能与离线包同时使用。

## 数据包

`build_offline_data.py` 把本地公开快照打包为 `offline/offline-data.json`：

```sh
python build_offline_data.py --huya-dir <本地虎牙快照目录> \
  --arammayhem-dir <本地 arammayhem 26.21 目录> \
  --output offline/offline-data.json
```

CI/构建机可省略本地目录，构建时从公开源抓取（运行时仍然完全离线）：

```sh
python build_offline_data.py --fetch --output offline/offline-data.json
```

`packaging/VGA-Aram-Helper.spec` 在构建时若存在该文件会把它打入 EXE；启动器默认使用它。

- 虎牙快照：英雄/强化名称与说明、历史英雄统计、出装名称。旧 T 级不用于本地档位。
- arammayhem 26.21（CC BY 4.0）：当前登场率/排名、英雄组合（god/trap）、装备 ID 与价格。
- 数据包不包含账号、Cookie、令牌、模型或厂商客户端代码。

## 本地档位

叠加层和资料页的 `S/A/B/C` 是**本地离线档位**，不是虎牙远端 AI 强度，也不是胜率：

1. 若离线快照包含该英雄的旧版英雄专属档位（`T1`–`T4`），映射为 `S/A/B/C` 作为基础；资料页标注“本地综合档位”，并注明基础来自 16.17 历史快照。
2. 没有英雄历史项时，以 arammayhem 当前登场率排名换算百分位：前 10% 为 S，前 30% 为 A，前 60% 为 B，其余为 C；标注“本地热度档位”。
3. 当前英雄组合 `god` 提升一档，`trap` 降低一档。
4. 若本轮三个候选中两项命中同一英雄组合，只应用一次并显示“本轮组合”：`god` 共同升一档，`trap` 共同降一档；不会因单项重复计数。
5. 未收录、重名、已退役条目显示“本地未收录”，不猜测。
6. 登场率文本随档位展示；不展示胜率、样本量或唯一最佳项。

这是可解释的本地近似：旧版英雄专属档位只用于本地基础，当前登场率/组合用于调整；不代表当前虎牙 AI 输出或当前强度统计。

## 已有功能

- 三个候选的名称 OCR、卡片边界/槽位、叠加层与资料页（既有截图识别链路）。
- 本地档位 + 登场率：资料页与卡片上方叠加层。
- 装备参考：公开源快照的出装名称；`导出推荐出装…` 可按离线装备 ID 生成推荐 JSON。
- 自动出装：在“设置”勾选“确认英雄后自动导出推荐出装”，可使用手动选择的目录，或自动使用已核验 LoL 安装下的
  `Config/Global/Recommended`（从游戏/客户端路径推导，仅使用已存在目录）。用户选择的目录优先；未检测到目录时不写入。
  默认关闭，绝不自动修改其他目录。
- 装备价值差：Tab 键触发本机 LCU 2999 只读读取，按离线装备价格计算已购装备价值差，浮层显示。
- 本机英雄身份：离线模式默认启用本机只读选人/本局身份；无头像缓存时仍可用 LCU 身份，HUD 头像仅作回退。

## Windows 便携测试包（内置运行时）

除源码运行外，可在带网络和 Linux/macOS 的构建机上组装“拷贝即用、运行时断网”的 Windows 便携包：

1. 下载 Python 3.12.10 embeddable `python-3.12.10-embed-amd64.zip` 并解压到 `python/`。
2. 用 `pip download --platform win_amd64 --python-version 3.12 --implementation cp --abi cp312 --only-binary=:all: -r requirements-build.txt -c packaging/windows-build-constraints.txt` 下载 Windows wheels，解压到 `python/Lib/site-packages`。
3. 把本仓库源码放到 `app/`，再放入 `app/offline/offline-data.json`。
4. `python312._pth` 增加 `Lib\site-packages`、`..\app` 和 `import site`。
5. 根目录放 `start.bat`：`..\python\python.exe launcher.py --offline --no-updates`；可另放 `smoke.bat` 运行 `--self-test`。
6. 连同 VC++ 运行库 DLL（若 wheels/embeddable 未自带）一起打包。

该便携包不是签名的正式 EXE，仍需在 Windows 上运行 `smoke.bat` 与实际对局验证。构建机需要联网；用户端解压后不需要联网。

## 边界

- 不包含虎牙远端 AI 模型或服务；本地档位是可解释的热度近似，不保证与虎牙输出一致。
- 出装名称来自旧快照，可能过期；资料页会标注。装备 ID 匹配按名称唯一匹配，未匹配项会跳过。
- 未在 Linux 上启动 Qt/Windows 捕获；Windows 视觉、真实对局与反作弊兼容性仍需实测。
- 推荐出装只写入用户选择的目录，不自动修改游戏目录；文件前缀 `!!!vga-aram-`。
- arammayhem 数据使用需署名并链接：`Data: arammayhem.com`，CC BY 4.0。
