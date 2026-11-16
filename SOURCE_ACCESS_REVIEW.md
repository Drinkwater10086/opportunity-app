# 附件未接入来源逐项复核（2026-11-16）

本轮逐项检查原来未接入的14个平台。HTTP状态只代表本次环境观察，不代表长期可用性，也不代表取得转载许可。官网、robots、官方订阅/开放平台文档交叉核验；未使用第三方RSSHub、内部接口逆向、登录Cookie或验证绕过。下面的“接入”指真实适配器，不是目录条目。

本轮新增 **InfoQ中国、量子位**，附件实际可采集平台由6增至8：GitHub、Stack Overflow、V2EX、IT之家、Kaggle、Product Hunt、InfoQ中国、量子位。其他来源仍不计入成功接入数量。

| 平台 | 本轮具体尝试及观察 | 当前处理与后续条件 |
|---|---|---|
| 哔哩哔哩 | 官网/robots可读；检查[官方开放平台](https://openhome.bilibili.com/doc)及[授权稿件查询](https://openhome.bilibili.com/doc/4/d9554788-dcef-f139-6217-b487d41c3826)说明 | 查询授权用户稿件不等于全站公开搜索；无适用应用权限，不写虚假全站适配器；转录也未实现 |
| 掘金 | 官网/robots可读，沿/terms转到当前[官方协议](https://juejin.cn/terms)；robots禁止/search | 协议6.1(2)涉及整理后站外展示需书面许可；当前应用用途未获许可，不调用网页内部API |
| InfoQ中国 | 复查[feed.xml](https://www.infoq.cn/feed.xml)为200/application/xml、有效RSS20项；robots的/feed/与/feed.xml是不同路径 | **已接入**。固定订阅、仅title/description，不补抓全文；适配器实测关键词AI/模型留6项、无日期或链接异常，1项未来日期被排除 |
| 少数派 | 官网明确声明/feed；重读[用户协议](https://sspai.com/page/agreement)“用户内容和使用原则”第4项第4款 | 自动化访问限制仍存在；有RSS不自动覆盖限制，等待适用例外许可 |
| CSDN | [官方博客页面](https://blog.csdn.net/blogdevteam/article/details/126135357)声明https://blog.csdn.net/blogdevteam/rss/map；实际访问该地址200/application/octet-stream但正文0字节，blog站robots可读 | 无有效XML，未把200空响应当成功；等待官方订阅恢复或其他明确接口，不尝试隐藏接口 |
| 机器之心 | 官网[数据服务](https://www.jiqizhixin.com/data-service)为登录入口；官方索引介绍免费RSS需申请开通；robots可读 | 未取得已开通的订阅地址，需账号持有人走官方申请流程并核对用途；免费RSS与付费MCP权益不混淆，不代购订阅 |
| 量子位 | 官网alternate声明[feed](https://www.qbitai.com/feed)，复查200/application/rss+xml、有效RSS10项，robots未禁止路径 | **已接入**。仅description摘要，不采用content:encoded全文、不取评论/图片；适配器实测AI/模型留2项，无日期或链接异常 |
| 36氪 | [官方RSS中心](https://www.36kr.com/rss-center)可读且列出/feed；再次请求https://36kr.com/feed与/robots.txt仍为200/text/html验证页 | 未将验证HTML解释为RSS或robots允许；等待官方端恢复，不绕过验证或切换代理试图规避 |
| 阿里云开发者社区 | 官网/indexFeed/为200/HTML文章列表，并非RSS；robots禁止搜索；找到[社区用户服务协议](https://developer.aliyun.com/article/970821)2.8 | 该条限制自动化接入、收集和处理内容；由“接口待核验”改为明确条款限制，等待适用授权，不能因HTML可读而采集 |
| Papers with Code | 原站再次302到https://huggingface.co/papers/trending | 不跟随后冒充原站采集；替代平台需要单列来源及独立核验 |
| Semantic Scholar | 重读[官方API许可](https://api.semanticscholar.org/license)2(a)、2(b)及公开署名条件 | 未解决当前匿名公网演示与内部研究/第三方分发条件的适配问题；不声称该API对所有研究都不可用，也不直接在公开站启用 |
| 天池 | 官网公开/dataset导航及精选数据卡片可读；检查[平台说明](https://tianchi.aliyun.com/specials/promotion/about)、[逐数据集许可指南](https://tianchi.aliyun.com/specials/promotion/license)与robots | 尚未核实当前用途适用的稳定公开目录接口；数据文件按单项许可另查，不将云市场天气/股票API误称为天池数据集搜索API |
| DataFountain | 官网数据集导航可读，robots404；重读[服务协议](https://www.datafountain.cn/help/service)知识产权第1条 | 未经书面许可使用、复制和传播存在限制；公开下载供竞赛使用不自动成为本站收集/再展示许可，等待适用授权 |
| 数睿思 | 官网可读，实际资源库/zyk/index.jhtml返回短脚本壳，竞赛导航指向同主机10010端口；robots404 | 仍未验证合法稳定内容接口；不把该端口和页面壳当作已接通竞赛数据，不探测端口/猜内部API |

团队可处理的具体步骤见[来源接入协作说明](SOURCE_AUTH_GUIDE.md)，区分账号开通、平台许可、接口恢复及程序开发，未将12个问题全部转交用户。

## 新订阅的数据边界

两源都在固定域名及文章路径白名单中运行，执行robots检查、请求间隔、4MB响应上限、时间窗口、关键词本地筛选、去重和隐私脱敏。403/429/异常XML显式失败，不静默转到抓文章全文。

InfoQ本次description只有“点击查看原文”链接：该导航提示移除后正文为空，保存body_available=false、news_headline、technical_context，不用标题单独认定用户需求。真正提供摘要时保存news_excerpt/secondary_report。量子位只使用description，不采用可能更长的content:encoded。摘要和标题也保留权利人版权，不将订阅开放描述成自由转载许可。

原始HTTP复核与真实采集快照仅在本机留存，公开Git只保存代码、说明和合成测试。测试结果及网站批次验证见SOURCES.md；时间变化导致实时数量变化，不能把跨时点计数当作单变量实验。
