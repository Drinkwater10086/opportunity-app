"""Collection-time content roles, shared with opportunity screening.

Related public records stay in result1; clear noise is forced to 0 in result2.
Signals refer to the record's own text, not an inherited discussion title alone.
"""
import re

import context_rules
import local_preprocessing

VERSION = 'collection-content-screening-v1'
LABELS = {'job_posting': '招聘信息', 'job_seeking': '求职信息',
          'product_promotion': '产品推广或发布', 'unclassified': '未命中前置排除规则'}
HIRING_THREAD = re.compile(r'^\s*(?:Ask HN:\s*)?Who is hiring\s*\??(?:\s|$)', re.I)
SEEKING_THREAD = re.compile(r'^\s*(?:Ask HN:\s*)?Who wants to be hired\s*\??(?:\s|$)|^\s*(?:求职|求职自荐|个人求职)(?:[\s:：|—-]|$)', re.I)
HIRING_ACTION = re.compile(
    r"\b(?:we(?:['’]re| are)?\s+(?:hiring|looking for|seeking)|join our team)\b"
    r'[^.!?\n]{0,100}\b(?:engineers?|developers?|candidates?|designers?|researchers?|managers?|team)\b|'
    r'(?:诚聘|招聘岗位|岗位职责|招募)[^。！？\n]{0,60}(?:工程师|开发|设计师|研究员|员工|岗位)', re.I)
JOB_DETAILS = re.compile(r'\b(?:compensation|salary|apply|full[ -]time|part[ -]time|benefits|equity|employment)\b|薪资|投递简历|任职要求|工作地点', re.I)
SEEKING_ACTION = re.compile(r"\b(?:I am|I'm|I’m|I have been)\s+(?:currently\s+)?looking for\s+(?:an?|my next)\s+(?:job|role|position)\b|\bavailable for (?:hire|employment)\b|(?:本人|我)(?:正在)?求职|求职意向", re.I)
LAUNCH_TITLE = re.compile(r'^\s*Show HN\s*:|^\s*(?:I|we)\s+(?:built|made|launched)\b|新品发布|产品发布|产品上线', re.I)
OWNER = re.compile(r"\b(?:I|we)\s+(?:(?:have|just|recently|also)\s+)*(?:built|made|created|launched|released|redesigned|started building)\b|\b(?:our|my)\s+(?:product|tool|platform|API)\b|(?:我们|我)(?:开发|推出|发布|上线)了", re.I)
PITCH = re.compile(r'\b(?:API|tool|platform|system|app)\s+(?:(?:helps?|can|will)\s+)?(?:automate\w*|convert\w*|extract\w*|capture\w*|generate\w*|reduce\w*|enable\w*|allow\w*)\b|\b(?:key features|main features|try (?:our|it)|sign up|buy now|free trial|pricing|early access|free subscription|provide a demo)\b|立即购买|免费试用|立即注册|产品功能', re.I)
BENEFIT = re.compile(r'\b(?:more efficiently|simplif\w* [^.!?\n]{0,40}(?:workflows?|reconciliation|process\w*)|improv\w* [^.!?\n]{0,40}(?:visibility|efficiency|accuracy)|reduce\w* manual|save\w* time|cut(?:s)? down on)\b|减少人工|提升效率|节省时间|降低成本', re.I)
LINK_EXCHANGE = re.compile(r'\b(?:friendly\s+)?(?:link|backlink)\s+exchange\s+(?:request|proposal)|\bexchange\s+(?:backlinks|links)\b|友链互换|交换友情链接|链接交换申请', re.I)
DOMAIN_PITCH = re.compile(r'\b[a-z0-9][a-z0-9.-]+\.(?:com|ai|io|app|me|net|co)\s+(?:can|helps?|lets?|allows?|provides?)\s+(?:\w+\s+){0,4}(?:surface|generate|produce|automate|extract|build|find)\w*\b', re.I)
REQUEST = re.compile(
    r"\b(?:(?:I|we|our team|my team)\s+(?:(?:still|really|currently|urgently|also)\s+)*(?:need|want|am looking for|are looking for)|how (?:can|do|should) (?:I|we))\b"
    r'[^.!?\n]{0,160}\b(?:extract\w*|summar\w*|classif\w*|screen\w*|match\w*|analy[sz]\w*|automat\w*|transcri\w*|retriev\w*|tool|solution)\b|'
    r'(?:我们|我|团队)(?:目前|仍然|现在)?(?:需要|希望|想要)[^。！？\n]{0,80}(?:抽取|提取|摘要|分类|筛选|匹配|自动化|转写|工具|方案)', re.I)
QUESTION = re.compile(r'\b(?:how (?:can|do|should) (?:I|we)|how to|can (?:anyone|someone) help|does anyone know|help me)\b|(?:求助|如何|有没有工具|求推荐)', re.I)


def inspect(title, content, provenance=None, *, view=None):
    """Return auditable labels without dropping, editing or truncating the record."""
    if view is None:
        view = local_preprocessing.structure(content)['text']
    provenance = provenance or {}
    comment = provenance.get('item_type') in ('comment', 'reply')
    # On comments, title belongs to the parent thread; explicit body requests win.
    request = REQUEST.search(view)
    question = QUESTION.search(view) or (None if comment else QUESTION.search(title))
    problem = context_rules.PERSONAL_PROBLEM.search(view)
    exception = bool((request and (question or problem)) or (question and problem))
    cues = []

    def cue(pattern, value, origin='content'):
        match = pattern.search(value)
        if match:
            original = content if origin == 'content' else title
            cues.append({'origin': origin, 'start': match.start(), 'end': match.end(),
                         'text': original[match.start():match.end()]})
        return bool(match)

    seeking = cue(SEEKING_THREAD, title, 'title') or cue(SEEKING_ACTION, view)
    hiring_thread = cue(HIRING_THREAD, title, 'title')
    hiring = cue(HIRING_ACTION, view)
    job_details = cue(JOB_DETAILS, view)
    link_exchange = cue(LINK_EXCHANGE, view) or cue(LINK_EXCHANGE, title, 'title')
    domain_pitch = cue(DOMAIN_PITCH, view)
    launch = False if comment else cue(LAUNCH_TITLE, title, 'title')
    owner = cue(OWNER, view)
    pitch = cue(PITCH, view)
    benefit = cue(BENEFIT, view)
    old_showcase = context_rules.showcase_status(title, view)
    structured_job = context_rules.job_posting_status(title, view)
    role = 'unclassified'
    if seeking:
        role = 'job_seeking'
    elif hiring_thread or (hiring and job_details) or structured_job['exclude']:
        role = 'job_posting'
    elif link_exchange or domain_pitch or (launch and (provenance.get('item_type') == 'story' or owner or pitch)) or (owner and pitch) or (pitch and benefit) or old_showcase['exclude']:
        role = 'product_promotion'
    # Explicit application-task questions survive even in a hiring/launch thread.
    # A link-exchange request is promotional regardless of generic task vocabulary.
    excluded = role != 'unclassified' and (link_exchange or not exception)
    if not cues and old_showcase['exclude']:
        for key in ('author_cue', 'features_cue', 'mechanism_cue', 'capability_cue'):
            if old_showcase.get(key):
                cues.append({'origin': 'content', **old_showcase[key]})
    return {'version': VERSION, 'stage': 'collection', 'role': role, 'label': LABELS[role], 'exclude': bool(excluded),
            'signals': cues, 'request_exception': bool(role != 'unclassified' and exception and not link_exchange),
            'exception_evidence': {'request': context_rules.span(request), 'problem': context_rules.span(problem)},
            'action': 'retain_and_force_non_opportunity' if excluded else 'retain_for_opportunity_screening'}


def summarize(reports):
    counts = {}
    for report in reports:
        if report['exclude']:
            counts[report['role']] = counts.get(report['role'], 0) + 1
    return {'version': VERSION, 'examined_count': len(reports), 'quarantined_count': sum(counts.values()),
            'by_role': counts, 'retained_in_result1': True}
