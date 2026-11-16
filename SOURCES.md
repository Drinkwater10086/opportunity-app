# 来源与内容形式（2026-11-14 核对）

补充核验（2026-11-15）：本轮仅通过既有官方API进行小规模公开Issue/问答检验。GitHub可接受使用政策允许研究使用公开非个人信息，要求由此发表的研究成果开放获取；并不允许任意个人信息采集或过量自动访问。见[GitHub官方政策](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies)。Stack Exchange要求遵守backoff，避免一分钟内重复语义相同请求，见[官方节流说明](https://api.stackexchange.com/docs/throttle)。本次读取API主机robots：api.github.com返回404、api.stackexchange.com返回400，均未获得可解析规则；不能写成robots明确授权。按官方API接口和限制使用，不绕过访问控制；最终发表、数据处理和共享仍须符合相关条件。

赛事附件2列出了哔哩哔哩、GitHub、Product Hunt、掘金、InfoQ中国、少数派、CSDN、机器之心、量子位、36氪、IT之家、V2EX、Stack Overflow、阿里云开发者社区、Papers with Code、Semantic Scholar、Kaggle、天池、DataFountain、数睿思。附件是参考清单，不是对抓取或再分发的授权。

| 来源 | 当前接入与范围 | 数据形式及证据边界 |
|---|---|---|
| GitHub（附件） | 公开项目搜索、公开Issue搜索 | JSON；项目简介和Markdown问题正文分别留痕，不把简介当README全文 |
| Stack Overflow（附件） | 公开问题API | JSON内HTML正文；保留各帖返回的许可说明及互动统计 |
| V2EX（附件，本次新增） | `https://www.v2ex.com/api/topics/latest.json` | JSON内Markdown正文，缺失时转HTML正文；只筛选接口当前返回的最新主题，不是历史搜索；不保存member、头像、作者档案或回复者身份 |
| arXiv（补充学术类，本次新增） | `https://rss.arxiv.org/rss/cs.AI` | RSS/Atom论文摘要；仅当日cs.AI订阅，可能为空；作为技术背景，不单独进入需求候选；不下载PDF或全文 |
| IT之家（附件，2026-11-16新增） | 官方RSS当前条目 | 标题与订阅摘要，二手报道；不补抓全文、评论或图片 |
| Kaggle（附件，2026-11-16新增） | 公开数据集目录API | 仅公开目录元数据，按更新时间过滤，技术资源；不下载文件或作者资料 |
| Hacker News、Super User、The Workplace、Node-RED | 保留现有适配器与限制 | 问题/讨论、外链标题或论坛正文；以每条provenance记录为准 |
| n8n、Make | 保持停用 | 已发现服务条款限制，不能因接口可访问而启用 |
| 少数派（附件） | 未启用 | 用户协议“用户内容和使用原则”4.4禁止自动机器人、爬虫、数据挖掘工具，RSS存在不覆盖该限制 |
| Semantic Scholar（附件） | 未启用 | 已找到API协议，但再分发与公开演示条款需进一步确认；不把公开可查询等同公开数据许可 |
| 附件其余来源 | 未启用，逐项状态见文末及网页目录 | 区分访问限制、授权/令牌、重定向及待核验；视频和收费内容不绕过限制 |

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

## 社区与订阅的检索词边界修复（2026-11-15）

Node-RED论坛、V2EX和arXiv的本地筛选统一使用`ascii-word-boundary-and-tokens-v1`：每行一组、行内词AND、行间OR；ASCII词使用字母/数字/下划线边界，AI不再误命中email、chair或my_AI_module，RAG不匹配storage。AI会议、使用AI等中文混排及AI-powered仍可匹配。中文词按原文子串匹配，未宣称中文分词或完整语义检索。引号和GitHub高级语法不会被本地筛选器自动解释；它们只适用于相应平台官方搜索接口。调用官方GitHub/Stack Exchange搜索的路径未改为本地筛选。

匹配方法版本同时写入每条记录provenance与来源运行元数据；新规则不覆盖旧采集批次。真实社区批次B793CA99B4FA1返回27条，两个来源均成功；在这27条已保留正文上按新边界核对只有16条仍匹配AI或LLM。该同正文对照说明旧子串匹配引入了噪声，不能把另一次实时采集的全部数量变化都归因于修复，因为最新流也会变化。

本轮再次读取[Node-RED/OpenJS条款](https://discourse.nodered.org/tos)，其中非代码投稿按CC BY 4.0、具体项目协议和例外须另外遵守；帖子自述并不等于官方背书。运行时仍读取robots检查帖子接口，不读取被限制的搜索页面、成员档案或绕过限流。公开仓库未发布本次采集正文。完整回归253项通过，含词边界、中英混排、AND组合和适配器测试。

修复后另建B0D52FFF4B86A批次，两个来源成功，共25条；每条正文均通过新匹配核验，并保留query_match_method版本。其LC5A726B47FBE4375本地实验为0候选；离线重放input_verified、same_outputs均为true。该实时结果与原27条数量不能直接当作唯一变量实验，前述同正文27→16才是匹配规则对照。0候选不等于来源没有需求，规则泛化与漏判仍需研究。

## 统一记录

所有来源最终使用同一批次/记录结构：标题、原文留存文本、清洗文本、来源URL、发布日期、更新时间、采集时间、原平台热度、许可说明、来源与格式元数据。不同平台的星数、回复数、阅读数不直接相加；缺失热度保持缺失。

新来源provenance记录：`transport_format`（json/rss/atom）、`content_format`（text/markdown/html）、`content_kind`（discussion/abstract）、`evidence_role`（demand_signal/technical_context）、`date_basis`、命中检索词。日期未知或URL不属于固定来源域名的记录不会冒充正常采集。

HTML转文本不执行脚本，丢弃script/style/iframe/template；XML拒绝DTD和实体声明。纯文本与Markdown保留语义内容；格式层可处理已提供的SRT/VTT字幕文本，但目前没有上传入口，也不自动下载或识别音视频。图片、PDF、音频、视频不能用标题或简介伪装为全文。

明显联系方式和凭据通过既有规则脱敏；规则不能保证所有自由文本个人信息都被识别，导出和公开分享前需核查。公共Git仓库只提交代码、说明和合成测试，不提交采集正文、数据库或本地日志。

## GitHub检索范围与正文格式（v14）

GitHub官方说明Issue默认搜索标题、正文和评论，而当前适配器仅留存标题与主帖。因此默认添加 `in:title,body`，使检索范围与保留字段一致；用户明确填写未加引号的 `in:` 限定时尊重原查询，并提示评论未采集。引号内的文字 `"in:comments"` 不算限定。每页实际params及每条provenance保存search_scope，旧批次不改写。依据：[Issue搜索范围](https://docs.github.com/en/search-github/searching-on-github/searching-issues-and-pull-requests)、[REST搜索API](https://docs.github.com/en/rest/search/search?apiVersion=2022-11-28)。这不能保证搜索结果必然符合业务方向。

GitHub Issue的JSON body是Markdown字符串，不再使用HTML转文本器处理；例如 `List<T>`、换行和围栏代码均保留。body返回异常非字符串时该页报错，不伪造正文。仍执行既有隐私脱敏；retained_body_sha256是**脱敏后保留正文**的UTF-8哈希，不是原HTTP字节哈希。provenance区分transport_format=json/content_format=markdown。分析阶段另行等长屏蔽隐藏内容，清洗原文与分析视图分开。旧批次中已被转换丢失的字符无法恢复。

## 附件2逐项接入与实测（2026-11-16）

按本地附件2.xlsx逐行核对，实际为20个平台。source_catalog.py保存全部条目、状态、范围及官方依据，GET /api/source-catalog及网页状态目录展示；目录不是适配器完成声明。当前附件内启用GitHub、Stack Overflow、V2EX、IT之家、Kaggle、Product Hunt、InfoQ中国、量子位；其余状态如下，不计作有效采集来源。

新增IT之家采用[官方RSS说明](https://www.ithome.com/0/000/037.htm)及当前主页alternate链接提供的https://www.ithome.com/rss/。本机初检RSS200/XML、robots200且未禁止此路径。只保留订阅提供的标题/摘要，不补抓全文、评论和图片，标记secondary_report/news_excerpt；媒体转述未经独立核实，版权不因RSS开放就失效。

新增Kaggle使用[官方API文档](https://www.kaggle.com/docs/api)及[官方API项目](https://github.com/Kaggle/kaggle-api/blob/main/docs/README.md)列出的公开数据集目录接口 /api/v1/datasets/list，实际匿名请求200/JSON。只使用search、page参数；pageSize在本次接口未按请求生效，因此不使用。每组最多3页，客户端日期与上限筛选；429/异常页保留此前成功页并标记部分完成。仅isPrivate=false项，保存标题、副标题/描述、资源URL、许可字段及非个人热度；不保存作者/成员档案，不下载数据文件。lastUpdated为过滤日期，published_at未知留空，不能改称发布时间。资料标记technical_context/dataset_metadata，不能单独成为需求机会。robots本次404不是明确授权；按平台公开接口及使用条件处理，数据集许可也不自动覆盖元数据全部用途。

| 平台 | 当前核验结果与处理 |
|---|---|
| 哔哩哔哩 | [开放平台协议](https://open.bilibili.com/agreement/developer-service)需适用权限，未取得；不抓取非授权接口、不伪造转录 |
| Product Hunt | GraphQL接口需token；官方MCP的search_launches工具当前明确标记noauth，匿名调用已成功；已接入这一个只读工具，不需要账户授权 |
| 掘金、阿里云开发者社区 | 本轮已核实站外展示/自动化采集限制，待适用许可；见后续复核文档 |
| CSDN | 官方页面声明的RSS本轮200但正文为空，未获得有效订阅 |
| InfoQ中国 | 首轮451，本轮feed.xml恢复有效RSS，现已接入标题/摘要；仅链接条目正文保持为空 |
| 少数派 | 既有用户协议核查发现自动化限制，仍未取得例外授权 |
| 机器之心 | 官方RSS需申请开通，匿名数据服务页显示登录；尚无已开通地址 |
| 量子位 | 首轮feed403，本轮恢复有效RSS，现已接入description摘要 |
| 36氪 | [官方RSS中心](https://www.36kr.com/rss-center)声明/feed，但本机/feed及robots返回HTML验证页；不当成RSS或允许采集 |
| Papers with Code | 原站本次302到https://huggingface.co/papers/trending，未把新站算成原站数据 |
| Semantic Scholar | [当前API许可](https://api.semanticscholar.org/license)含内部研究、公开署名及再分发条件，当前公开演示方案尚未完成核对，未启用 |
| 天池、数睿思 | 已检查官网目录和许可/资源入口，稳定可用接口仍未核实 |
| DataFountain | 本轮已核实内容复制传播条件，等待适用许可 |

新增robots检查拒绝HTML验证页，避免HTML被RobotFileParser当作无规则而误放行。上述HTTP仅是本次环境实测，不能保证持续可用，也不是分类正确性证据。真实响应/采集快照仍仅保存在本机，不提交公开Git。


Product Hunt核验更正：官方安装页介绍OAuth登录，但实际tools/list对search_launches声明readOnlyHint=true、securitySchemes=noauth；匿名tools/call已返回200及structuredContent.status=ok。因此不再把全部MCP操作都描述为必须授权，也不为公开检索请求账户权限。适配器固定工具名，单组最多8项、近1–365天，不伪造分页；只采用结构化name/tagline/description/url/launched_at/votes_count，不采用聊天文本、review摘要、makers、账户或其他操作。产品资料标记technical_context/product_metadata，未独立验证，不能单独进入需求候选。遵守[平台使用条件](https://www.producthunt.com/legal)及[官方API非商业使用边界](https://www.producthunt.com/v2/docs)，仅作非商业研究的有限产品资料；接口可读不是自由转载许可。认证失败时明确停止，未保存任何Product Hunt账户凭据。

真实验证：首批IT之家路径只接受旧/0/前缀，遇当前/1/文章导致部分完成；未修改旧批次。修复为数字前缀后新批次BA0FA62B93617共30条（IT之家10、Kaggle20），两源完整成功，程序实验LE915D8E069EB4ADE为0候选；离线重放input_verified与same_outputs均true。Kaggle记录发布时间均保持未知，更新时间存在，且仅作技术资源。0候选不等于市场不存在需求。Product Hunt适配器另一次实际只读查询AI返回3条、完整成功；记录仅留本机，不提交正文到公开仓库。

实际网站完整链路：Product Hunt批次B4CA6AC46567D采到8条，来源状态success；程序实验LE9308680D2994893完成，8条产品资料均不成为需求候选，离线重放输入校验和输出一致性通过。完整回归299项通过（另有一项既有AnyIO弃用警告）；测试通过不证明需求判别正确性。


## 14个未接入平台再次逐项尝试（2026-11-16）

逐项复核见[SOURCE_ACCESS_REVIEW.md](SOURCE_ACCESS_REVIEW.md)，包含每个平台具体入口、实际观察、未启用理由和后续条件。历史451/403是此前环境观察，不是永久结论：InfoQ中国feed.xml与量子位/feed本轮均返回有效RSS，现已接入。附件8个平台可采集，其余12个仍未接通。全站当前13个启用平台、14个采集选项；GitHub两种采集算同一网站。

InfoQ使用https://www.infoq.cn/feed.xml，robots的/feed/禁止项不匹配/feed.xml；仅订阅title/description。移除纯“点击查看原文”提示，未提供正文则保留空值及body_available=false，角色technical_context/news_headline，不用标题冒充需求证据。量子位只使用官网alternate声明的/feed及description，忽略content:encoded全文，不补抓正文。两源摘要有提供时角色为secondary_report/news_excerpt，未经独立核实。

阿里云开发者社区找到适用社区协议2.8自动化限制，掘金找到6.1站外整理展示限制，DataFountain找到复制传播需许可条件；已更新目录状态，不能继续统一写成“尚未核实接口”。CSDN官方博客声明的RSS本轮200但零字节，仍未接入。36氪仍是验证HTML；机器之心RSS需走官方申请开通，未取得地址；其余核验情况与条件均公开列明。没有使用Cookie、逆向接口、第三方镜像、验证码破解或生成式模型。

本轮网站实测批次B70964DBBC8F9：InfoQ中国6条、量子位2条，两源success；实验LBD4B4712228D485B完成，8条记录、0候选，离线input_verified与same_outputs均true。完整回归303项通过，有一项既有AnyIO弃用警告。浏览器已看到两个新选项、来源计数及原文列表；公网目录实测20项/8项enabled。测试与重放仅验证实现及一致性，不证明需求判别准确率。
