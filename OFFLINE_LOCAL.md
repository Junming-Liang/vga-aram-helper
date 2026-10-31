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

叠加层和资料页的 `S/A/B/C` 是**本地热度档位**，不是虎牙远端 AI 强度，也不是胜率：

1. 以 arammayhem 当前登场率排名换算百分位：前 10% 为 S，前 30% 为 A，前 60% 为 B，其余为 C。
2. 英雄组合标记 `god` 提升一档，`trap` 降低一档。
3. 未收录、重名、已退役条目显示“本地未收录”，不猜测。
4. 登场率文本随档位展示；不展示胜率、样本量或唯一最佳项。

## 已有功能

- 三个候选的名称 OCR、卡片边界/槽位、叠加层与资料页（既有截图识别链路）。
- 本地档位 + 登场率：资料页与卡片上方叠加层。
- 装备参考：公开源快照的出装名称；`导出推荐出装…` 可按离线装备 ID 生成推荐 JSON。
- 自动出装：在“设置”选择自动导出目录并勾选“确认英雄后自动导出推荐出装”，确认英雄后会写入用户选择的目录；默认关闭，绝不自动修改其他目录。
- 装备价值差：Tab 键触发本机 LCU 2999 只读读取，按离线装备价格计算已购装备价值差，浮层显示。
- 本机英雄身份：离线模式默认启用本机只读选人/本局身份；无头像缓存时仍可用 LCU 身份，HUD 头像仅作回退。

## 边界

- 不包含虎牙远端 AI 模型或服务；本地档位是可解释的热度近似，不保证与虎牙输出一致。
- 出装名称来自旧快照，可能过期；资料页会标注。装备 ID 匹配按名称唯一匹配，未匹配项会跳过。
- 未在 Linux 上启动 Qt/Windows 捕获；Windows 视觉、真实对局与反作弊兼容性仍需实测。
- 推荐出装只写入用户选择的目录，不自动修改游戏目录；文件前缀 `!!!vga-aram-`。
- arammayhem 数据使用需署名并链接：`Data: arammayhem.com`，CC BY 4.0。
