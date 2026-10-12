# 来源与独立实现说明

## 证据范围

参考入口：https://gametool.huya.com/lolhex

本原型已实现的参考行为来自对公开网站的静态分析。另行对真实桌面客户端的静态分析显示 Electron/React、Windows 原生截图/悬浮层与远程 AI 服务组件；这些组件与后端能力未在本原型中重建。分析中没有执行目标应用。公开网页行为不能证明 Windows 桌面产品的内部实现、游戏识别方式或运行时数据来源。

本项目的 Python、HTML、CSS、JavaScript 和演示数据均为新写实现。没有复用目标 UI、品牌图标、图片、提取代码或运行时脚本。此包只实现手动参考资料工作流。

已从行为证据独立重述并实现的部分包括：名称/别名搜索、定位/稀有度筛选、特殊联动/陷阱读取、max 去重的装备规则分、中文同分排序和浏览器本地收藏。

## 曾验证的公开数据快照 URL

这些 URL 在 2026-10-12 UTC 的研究中被验证。内容最新性、使用授权与长期可用性不能由此推定。本包不自动请求它们，也不附带内容。

- https://huyafedltc.msstatic.com/gametool/league-of-legends/work/assets/heroIndex-CuWQeg2k.json
- https://huyafedltc.msstatic.com/gametool/league-of-legends/work/assets/augments-CcCw5SNQ.json
- https://huyafedltc.msstatic.com/gametool/league-of-legends/work/assets/items-DcZ4G5oX.json
- https://huyafedltc.msstatic.com/gametool/league-of-legends/work/assets/relations-CFaVM0ij.json
- https://huyafedltc.msstatic.com/gametool/league-of-legends/work/assets/combinations-z-aDMf_y.json
- https://huyafedltc.msstatic.com/gametool/league-of-legends/work/assets/changelogs-C1-QQJxS.json

最新可见日志条目日期：2026-07-17。顶层日志对象另有 2026-02-04 的 `last_update`，两者口径不同，不可混用。没有证据表明这些胜率是 2026-10-12 的实时统计。

## 有意省略

- 原站广告、账号、兑换、订阅、排名积分、追踪和外部资源
- 百分位强度等级，因为它们只是展示层排序标签，不能当作独立性能结论
- 自动游戏识别、客户端连接、键鼠自动操作、屏幕读取、Windows 打包
- 没有提供的配对胜率、样本量、当前版本校验和置信度

原项目的数据及其游戏名称可能属于对应权利人。本包没有为其数据再分发作授权判断。
