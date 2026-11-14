# 来源与内容形式（2026-11-14 核对）

赛事附件2列出了哔哩哔哩、GitHub、Product Hunt、掘金、InfoQ中国、少数派、CSDN、机器之心、量子位、36氪、IT之家、V2EX、Stack Overflow、阿里云开发者社区、Papers with Code、Semantic Scholar、Kaggle、天池、DataFountain、数睿思。附件是参考清单，不是对抓取或再分发的授权。

| 来源 | 当前接入与范围 | 数据形式及证据边界 |
|---|---|---|
| GitHub（附件） | 公开项目搜索、公开Issue搜索 | JSON；项目简介和Markdown问题正文分别留痕，不把简介当README全文 |
| Stack Overflow（附件） | 公开问题API | JSON内HTML正文；保留各帖返回的许可说明及互动统计 |
| V2EX（附件，本次新增） | `https://www.v2ex.com/api/topics/latest.json` | JSON内Markdown正文，缺失时转HTML正文；只筛选接口当前返回的最新主题，不是历史搜索；不保存member、头像、作者档案或回复者身份 |
| arXiv（补充学术类，本次新增） | `https://rss.arxiv.org/rss/cs.AI` | RSS/Atom论文摘要；仅当日cs.AI订阅，可能为空；作为技术背景，不单独进入需求候选；不下载PDF或全文 |
| Hacker News、Super User、The Workplace、Node-RED | 保留现有适配器与限制 | 问题/讨论、外链标题或论坛正文；以每条provenance记录为准 |
| n8n、Make | 保持停用 | 已发现服务条款限制，不能因接口可访问而启用 |
| 少数派（附件） | 未启用 | 用户协议“用户内容和使用原则”4.4禁止自动机器人、爬虫、数据挖掘工具，RSS存在不覆盖该限制 |
| Semantic Scholar（附件） | 未启用 | 已找到API协议，但再分发与公开演示条款需进一步确认；不把公开可查询等同公开数据许可 |
| 附件其余来源 | 尚未实现 | 必须逐一核验官方访问方法、条款、robots及内容权利；视频和收费内容不绕过限制 |

## 已核对的官方依据

- V2EX当前API说明：https://www.v2ex.com/help/api （2.0需要个人令牌；本程序不请求令牌、不访问个人接口；公开旧latest端点另作实时结构校验，未来可能不可用）
- V2EX公开端点：https://www.v2ex.com/api/topics/latest.json
- V2EX站点规则：https://www.v2ex.com/about ，robots：https://www.v2ex.com/robots.txt （本次返回200，没有禁止所用路径）。原帖权利归作者，不能据此推断任意转载许可。
- arXiv官方RSS说明：https://info.arxiv.org/help/rss.html
- arXiv API条款：https://info.arxiv.org/help/api/tou.html （描述性元数据包括摘要，CC0；RSS等旧接口最多每3秒一次、单连接；全文另受著作权约束）
- arXiv robots说明：https://info.arxiv.org/help/robots.html 。`export.arxiv.org/robots.txt`返回全站Disallow，因此本次没有接该主机的搜索API；`rss.arxiv.org/robots.txt`返回404，使用官方明确提供的RSS服务。
- 少数派用户协议：https://sspai.com/page/agreement
- Semantic Scholar API协议：https://api.semanticscholar.org/license/

新增适配器运行时检查robots，最多缓存规则6小时；网络错误、403、限流或拒绝采集时显式失败，不绕过、不切换镜像、不追踪未知重定向。V2EX请求至少间隔10秒；arXiv至少3秒。最多读取4MB响应，超限报错。订阅每行检索词OR、行内空白分词AND，本地筛选，不支持搜索引擎高级语法。

## 统一记录

所有来源最终使用同一批次/记录结构：标题、原文留存文本、清洗文本、来源URL、发布日期、更新时间、采集时间、原平台热度、许可说明、来源与格式元数据。不同平台的星数、回复数、阅读数不直接相加；缺失热度保持缺失。

新来源provenance记录：`transport_format`（json/rss/atom）、`content_format`（text/markdown/html）、`content_kind`（discussion/abstract）、`evidence_role`（demand_signal/technical_context）、`date_basis`、命中检索词。日期未知或URL不属于固定来源域名的记录不会冒充正常采集。

HTML转文本不执行脚本，丢弃script/style/iframe/template；XML拒绝DTD和实体声明。纯文本与Markdown保留语义内容；格式层可处理已提供的SRT/VTT字幕文本，但目前没有上传入口，也不自动下载或识别音视频。图片、PDF、音频、视频不能用标题或简介伪装为全文。

明显联系方式和凭据通过既有规则脱敏；规则不能保证所有自由文本个人信息都被识别，导出和公开分享前需核查。公共Git仓库只提交代码、说明和合成测试，不提交采集正文、数据库或本地日志。
