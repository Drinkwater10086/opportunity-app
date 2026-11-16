"""Contest attachment 2 inventory. An inventory entry is not a working adapter."""
REVIEWED_ON='2026-11-16'
ENTRIES=[
    ('bilibili','哔哩哔哩','https://www.bilibili.com/','needs_permission','开放平台接口需要适用授权，未获取；未实现视频转录','https://open.bilibili.com/agreement/developer-service'),
    ('github','GitHub','https://github.com/','enabled','项目简介与Issue主帖两种采集，不采评论','https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies'),
    ('producthunt','Product Hunt','https://www.producthunt.com/','enabled','官方MCP的search_launches标记noauth且匿名实测成功；每组最多8项产品简介，仅作技术资源','https://www.producthunt.com/mcp/install'),
    ('juejin','掘金','https://juejin.cn/','pending_review','尚未核实适用公开采集接口及使用条件','https://juejin.cn/'),
    ('infoq','InfoQ中国','https://www.infoq.cn/','access_unavailable','候选feed.xml在本次环境返回451，未取得有效订阅数据','https://www.infoq.cn/article/2014/02/infoq-topics-rss'),
    ('sspai','少数派','https://sspai.com/','policy_restricted','既有协议核查发现自动化访问限制，未获得例外许可','https://sspai.com/page/agreement'),
    ('csdn','CSDN','https://www.csdn.net/','pending_review','博客内容适用接口及条款未确认；不套用其他产品的协议结论','https://www.csdn.net/'),
    ('jiqizhixin','机器之心','https://www.jiqizhixin.com/','pending_review','官方数据服务页显示登录入口，公开RSS地址和使用权限未核实','https://www.jiqizhixin.com/data-service'),
    ('qbitai','量子位','https://www.qbitai.com/','access_unavailable','官网声明的/feed本次返回403，未绕过限制','https://www.qbitai.com/'),
    ('36kr','36氪','https://36kr.com/','access_unavailable','官方RSS与robots请求返回HTML验证页，不能当有效数据或采集许可','https://www.36kr.com/rss-center'),
    ('ithome','IT之家','https://www.ithome.com/','enabled','已接入官方RSS摘要，不补抓全文、评论或图片','https://www.ithome.com/0/000/037.htm'),
    ('v2ex','V2EX','https://www.v2ex.com/','enabled','仅最新公开接口当前主题，不是历史搜索','https://www.v2ex.com/help/api'),
    ('stackoverflow','Stack Overflow','https://stackoverflow.com/','enabled','官方公开问题接口，遵守共享配额与backoff','https://api.stackexchange.com/docs/throttle'),
    ('aliyun','阿里云开发者社区','https://developer.aliyun.com/','pending_review','尚未核实稳定公开搜索/订阅接口与适用使用条件','https://developer.aliyun.com/'),
    ('paperswithcode','Papers with Code','https://paperswithcode.com/','redirected','原站本次302到Hugging Face Papers，不冒充仍从原平台采集','https://paperswithcode.com/'),
    ('semanticscholar','Semantic Scholar','https://www.semanticscholar.org/','license_review','API许可对公开展示、署名及再分发有条件，尚未完成当前演示方案核对','https://api.semanticscholar.org/license'),
    ('kaggle','Kaggle','https://www.kaggle.com/','enabled','官方公开数据集目录元数据；仅技术资源，不下载文件或当作用户需求','https://www.kaggle.com/docs/api'),
    ('tianchi','天池','https://tianchi.aliyun.com/','pending_review','竞赛/数据集公开接口及下载授权范围尚未核实','https://tianchi.aliyun.com/'),
    ('datafountain','DataFountain','https://www.datafountain.cn/','pending_review','官网可访问，尚未核实适用公开数据接口与再利用范围','https://www.datafountain.cn/'),
    ('tipdm','数睿思','https://www.tipdm.org/','pending_review','附件所列官网可访问，稳定竞赛/数据集入口及使用条件尚未核实','https://www.tipdm.org/'),
]
STATUS_LABELS={'enabled':'已接入','needs_permission':'需要授权','needs_token':'需要平台令牌',
               'pending_review':'待核验接口与条件','access_unavailable':'本次访问受限',
               'policy_restricted':'条款限制','redirected':'原站重定向','license_review':'许可条件待核对'}


def report():
    return {'attachment':'附件2.xlsx','reviewed_on':REVIEWED_ON,
            'note':'目录覆盖附件全部20个平台；仅“已接入”条目有启用适配器，其余不计作可用采集来源。来源可用性会变化，实际以批次来源日志为准。',
            'entries':[{'id':key,'name':name,'homepage':url,'status':status,'status_label':STATUS_LABELS[status],
                        'note':note,'evidence_url':evidence} for key,name,url,status,note,evidence in ENTRIES]}
