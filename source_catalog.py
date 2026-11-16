"""Contest attachment 2 inventory. An inventory entry is not a working adapter."""
REVIEWED_ON='2026-11-16'
ENTRIES=[
    ('bilibili', '哔哩哔哩', 'https://www.bilibili.com/', 'needs_permission', '官方开放平台视频查询针对授权用户稿件，当前无开发者应用权限；不是全站公开视频检索接口，未实现转录', 'https://openhome.bilibili.com/doc/4/d9554788-dcef-f139-6217-b487d41c3826'),
    ('github','GitHub','https://github.com/','enabled','项目简介与Issue主帖两种采集，不采评论','https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies'),
    ('producthunt','Product Hunt','https://www.producthunt.com/','enabled','官方MCP的search_launches标记noauth且匿名实测成功；每组最多8项产品简介，仅作技术资源','https://www.producthunt.com/mcp/install'),
    ('juejin', '掘金', 'https://juejin.cn/', 'needs_permission', '已读协议6.1(2)，站外整理展示需书面许可；robots也禁止/search，未使用内部接口', 'https://juejin.cn/terms'),
    ('infoq', 'InfoQ中国', 'https://www.infoq.cn/', 'enabled', '官方feed.xml本轮复测返回有效RSS，已接入当前标题/摘要；部分记录只有标题和原文链接', 'https://www.infoq.cn/feed.xml'),
    ('sspai','少数派','https://sspai.com/','policy_restricted','既有协议核查发现自动化访问限制，未获得例外许可','https://sspai.com/page/agreement'),
    ('csdn', 'CSDN', 'https://www.csdn.net/', 'access_unavailable', '官方博客页面声明的blogdevteam/rss/map本轮HTTP200但正文为空；未把空响应视作有效订阅', 'https://blog.csdn.net/blogdevteam/article/details/126135357'),
    ('jiqizhixin', '机器之心', 'https://www.jiqizhixin.com/', 'needs_permission', '官方数据服务有RSS申请开通入口，匿名页面显示登录；未取得已开通的订阅地址，不绕过授权', 'https://www.jiqizhixin.com/data-service'),
    ('qbitai', '量子位', 'https://www.qbitai.com/', 'enabled', '官网声明的/feed本轮复测为有效RSS，已接入description摘要；不补抓全文', 'https://www.qbitai.com/'),
    ('36kr','36氪','https://36kr.com/','access_unavailable','官方RSS与robots请求返回HTML验证页，不能当有效数据或采集许可','https://www.36kr.com/rss-center'),
    ('ithome','IT之家','https://www.ithome.com/','enabled','已接入官方RSS摘要，不补抓全文、评论或图片','https://www.ithome.com/0/000/037.htm'),
    ('v2ex','V2EX','https://www.v2ex.com/','enabled','仅最新公开接口当前主题，不是历史搜索','https://www.v2ex.com/help/api'),
    ('stackoverflow','Stack Overflow','https://stackoverflow.com/','enabled','官方公开问题接口，遵守共享配额与backoff','https://api.stackexchange.com/docs/throttle'),
    ('aliyun', '阿里云开发者社区', 'https://developer.aliyun.com/', 'policy_restricted', '社区用户服务协议2.8限制自动化接入和内容收集；indexFeed是HTML列表，未因可读而启用', 'https://developer.aliyun.com/article/970821'),
    ('paperswithcode','Papers with Code','https://paperswithcode.com/','redirected','原站本次302到Hugging Face Papers，不冒充仍从原平台采集','https://paperswithcode.com/'),
    ('semanticscholar','Semantic Scholar','https://www.semanticscholar.org/','license_review','API许可对公开展示、署名及再分发有条件，尚未完成当前演示方案核对','https://api.semanticscholar.org/license'),
    ('kaggle','Kaggle','https://www.kaggle.com/','enabled','官方公开数据集目录元数据；仅技术资源，不下载文件或当作用户需求','https://www.kaggle.com/docs/api'),
    ('tianchi', '天池', 'https://tianchi.aliyun.com/', 'pending_review', '已核对官网dataset导航、数据平台说明和逐数据集许可指南；未核实适用稳定公开目录接口，不下载文件', 'https://tianchi.aliyun.com/specials/promotion/license'),
    ('datafountain', 'DataFountain', 'https://www.datafountain.cn/', 'needs_permission', '官网与数据集导航可读，服务协议知识产权第1条限制未经书面许可复制及传播；未批量读取数据集', 'https://www.datafountain.cn/help/service'),
    ('tipdm', '数睿思', 'https://www.tipdm.org/', 'access_unavailable', '官网资源库入口zyk/index.jhtml本轮只有脚本跳转壳；竞赛入口另用10010端口，未验证适用接口', 'https://www.tipdm.org/zyk/index.jhtml'),
]
STATUS_LABELS={'enabled':'已接入','needs_permission':'需要授权','needs_token':'需要平台令牌',
               'pending_review':'待核验接口与条件','access_unavailable':'本次访问受限',
               'policy_restricted':'条款限制','redirected':'原站重定向','license_review':'许可条件待核对'}


def report():
    return {'attachment':'附件2.xlsx','reviewed_on':REVIEWED_ON,
            'note':'目录覆盖附件全部20个平台；仅“已接入”条目有启用适配器，其余不计作可用采集来源。来源可用性会变化，实际以批次来源日志为准。',
            'entries':[{'id':key,'name':name,'homepage':url,'status':status,'status_label':STATUS_LABELS[status],
                        'note':note,'evidence_url':evidence,'next_action':NEXT_ACTIONS.get(key,'已接入；可用性以本次采集日志为准')} for key,name,url,status,note,evidence in ENTRIES]}

NEXT_ACTIONS={
 'bilibili':'取得适用开发者权限并确认授权稿件范围；仍不能据此承诺全站搜索或视频转录',
 'juejin':'取得站外整理展示许可及适用数据接口说明',
 'csdn':'等待官方订阅返回有效XML，或获得其他官方公开接口依据',
 'jiqizhixin':'由账号持有人按官方数据服务流程申请开通，再核对订阅范围与用途；不在聊天里发送令牌',
 '36kr':'等待官方订阅及robots恢复有效响应；不破解验证页面',
 'sspai':'取得自动化访问的例外许可',
 'aliyun':'取得社区对当前研究采集用途的适用授权',
 'paperswithcode':'如改接Hugging Face Papers，须单列新平台并核对接口，不能算原平台恢复',
 'semanticscholar':'取得适合当前公开测试站用途的许可确认，并落实要求的署名与展示条件',
 'tianchi':'核实官方目录获取方式；具体数据文件另查每个数据集许可',
 'datafountain':'取得适合内容采集及当前公开展示的书面许可',
 'tipdm':'核实官网实际竞赛平台与合法稳定数据接口',
}
