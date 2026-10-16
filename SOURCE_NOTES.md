# 数据来源

## 英雄统计 wiki

主要数据来自[虎牙公开英雄统计 wiki](https://gametool.huya.com/league-of-legends/wiki/index.html?embed=1)。程序读取页面配置，通过匿名 `getGameToolVersion` 接口发现当前版本及数据目录，再获取以下文件：

- `champion-list.json`、`champion-detail.json`
- `augment-list.json`、`augment-detail.json`
- `item-detail.json`

英雄专属推荐来自 `champion-detail` 的 `augmentRecommendations`。内部导入/缓存保留数组顺序，以及各项的 `tier`、`winRate`、`pickRate`、`numGames`；玩家界面和公开 HTTP 响应只输出原始评级及机制资料，过滤胜率、选取率、样本量和推荐排名，不输出唯一最佳项。字段解释见 [DATA.md](DATA.md)，发现、验证和缓存流程见 [UPDATES.md](UPDATES.md)。

### 已检查快照

2026-10-12 检查的快照如下，不代表之后启动时获取的版本：

- 数据包：395
- 游戏资料版本：16.17
- 来源数据日期：2026-09-07
- 数据目录：<https://fileserver.cdn.huya.com/game_tools/1-p81hl812-395/395/>
- 内容：172 位英雄、209 个海克斯、180 件装备、21,288 条英雄与海克斯配对
- 缺失统计：1,582 条配对的胜率为空、样本量为 0

这些空值按原样保留。来源未公布的统计区间、地区及置信区间保持未知。快照检查记录见 [official-snapshot-v03.json](reports/official-snapshot-v03.json)。

## 旧版参考资料

[旧版海克斯图鉴](https://gametool.huya.com/lolhex) 使用 `heroIndex-*.json`、`augments-*.json`、`items-*.json`、`relations-*.json` 和 `combinations-*.json`。其中的联动、陷阱与装备关联以文字理由或关联分数表达。

这套资料可通过本地文件导入，当前自动更新不依赖它。已检查的旧快照日志止于 2026-07-17；其日期和分数不用于解释新版 wiki 的统计。

## 网络与再分发

程序将页面及前端脚本作为配置文本解析，不执行远端 JavaScript，不请求游戏图片、图标或字体。数据接口不需要用户账号、Cookie、令牌或目标助手凭据。

公开可访问不等于获得再分发许可。仓库不包含完整第三方数据集、真实游戏截图、目标客户端或网页源码、厂商品牌素材与凭据。使用及再分发数据前，请确认相关服务条款和权利人的许可。

## 实现来源

本项目依据公开数据协议和行为证据独立实现。`analysis/` 保存经过清理的协议摘要与虚构回放输入；它们用于研究和测试，不包含上游远程 AI 模型。项目不调用私有识别服务，也不使用目标客户端的嵌入凭据。
