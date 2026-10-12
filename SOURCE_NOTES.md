# 数据来源与版本边界

## v0.3 主路径：官方公开英雄统计 wiki

- 页面：https://gametool.huya.com/league-of-legends/wiki/index.html?embed=1
- 版本由该页面配置及匿名 `getGameToolVersion` 接口发现；不是写死“永远最新”的 CDN 路径。
- 2026-10-12 实际验证到的数据根路径：https://fileserver.cdn.huya.com/game_tools/1-p81hl812-395/395/
- 文件：`champion-list.json`、`champion-detail.json`、`augment-list.json`、`augment-detail.json`、`item-detail.json`。
- 当次数据版本395，源游戏资料版本16.17，源数据日期2026-09-07。获取时间不代表统计更新时间。

`champion-detail` 172位英雄具有21,288条英雄专属海克斯记录。每条保留源 `tier/winRate/pickRate/numGames` 与数组顺位；缺失胜率/样本不补零、不从全局值推算。来源未给明的统计区间、地区和置信度不推测。21,288条中1,582条胜率为空、样本为0。

旧调查只看到了另一套静态参考资料，**据此认为配对胜率没有公开提供的结论不完整，已在 v0.3 纠正**。新的实际数据和代码路径以本文件、README 和新验证报告为准。

网络更新实现只读取数据和配置，不执行来自网页/CDN 的脚本。程序不请求图标、字体或游戏图片；远端可执行文件只来自项目批准的 GitHub Release 更新流程，须经确认与校验。

## 可选旧参考资料

页面：https://gametool.huya.com/lolhex

旧参考数据使用 `heroIndex-*.json`、`augments-*.json`、`items-*.json`、`relations-*.json`、`combinations-*.json`。其中特殊联动/陷阱以文字理由表达；有条件或自相矛盾的记录，不能当作无条件评级。公开参考快照的日志曾止于2026-07-17，不能冒充新 wiki 的数据日期。

旧装备关联分数是原型的透明关联展示，不是胜率和英雄三选一推荐分。仍支持用户显式导入，当前正式自动更新不依赖旧静态文件名。

## 未授予的权限与未完成能力

公开可访问不等于获得再分发许可。源码仓库不包含捕获的完整数据集、真实截图、目标客户端/网页源码、厂商品牌资源或凭据；请自行确认服务条款和数据使用权限。

静态研究证明了真实桌面产品依赖原生采集与上游服务，未证明本项目已具备自动游戏识别、实时游戏悬浮层、完整远端 AI 等价模型或自动选牌。开发测试没有证明在所有游戏版本、分辨率或 Windows 机器上都正确。
