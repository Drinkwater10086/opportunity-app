"""Bounded lexical negation and content-intent rules; not full language understanding."""
import re

VERSION='negation-and-tutorial-v5'
DEPENDENCY_REFERENCE=re.compile(
    r'\s+(?:(?:issues?|PR)\s*)?#?\d+(?:[ \t]*(?:[,/&]|and)[ \t]*#?\d+)*(?:[ \t]*\(\s*#\d+\s*\))?'
    r'(?=[ \t]*(?:\r?\n|[.!?](?=\s|$)|$|In parts\s*:))',re.I)
NEGATIVE_PREFIX=re.compile(
    r"(?:\b(?:(?:do|does|did|would|should|could|can)\s+not|(?:don|doesn|didn|wouldn|shouldn|couldn|can)['’]t|no\s+longer|never|not|no|zero|avoid(?:s|ing)?)"
    r"(?:\s+(?:really|actually|currently|have|face|experience|any|an?|the|need|for))*\s*$|(?:不再|并不|不|无需|无须|没有必要|没必要|避免|免去|零)\s*$)",re.I)
TUTORIAL=re.compile(r'本教程|纯教程|入门教程|教程演示|本文将(?:教|介绍)|\b(?:this tutorial|pure tutorial|in this tutorial|this guide (?:shows|explains)|learn how to|step.by.step tutorial|beginner.s guide)\b',re.I)
PERSONAL_PROBLEM=re.compile(
    r'(?:(?:我们|我|团队)[^。！？\n]{0,100}(?:无法|失败|困难|耗时|遇到))|'
    r'\b(?:I|we|our team|my team)\b[^.!?\n]{0,100}\b(?:cannot|can.t|unable|struggl\w*|failed|failing|problem)\b',re.I)
SPECULATIVE_PREFIX=re.compile(
    r'(?:\b(?:may|might|could|perhaps|possibly|potentially)(?:\s+(?:also|eventually|someday|have|face|a|an|the))*\s*$|'
    r'(?:可能|或许|也许|假设)(?:将会|会|还|有|存在|一些)?\s*$)',re.I)
JOB_SIGNALS={
    'position':r'\b(?:vacanc(?:y|ies)|job\s+id|open position|we are hiring|employment type)\b|招聘岗位|职位编号|岗位职责',
    'application':r'\b(?:apply now|apply here|how to apply|application deadline|salary|benefits package)\b|投递简历|申请截止|薪资待遇',
    'listing':r'\b(?:description excerpt|matched queries|api status:\s*published_public)\b|职位描述',
}
USER_PROCESSING_TASK=re.compile(
    r'\b(?:I|we|our team)\b[^.!?\n]{0,50}\b(?:needs?|wants?|looking for)\b[^.!?\n]{0,80}'
    r'\b(?:extract|summariz\w*|classif\w*|screen|match|analy[sz]\w*|automat\w*)\b|'
    r'(?:我们|我|团队)[^。！？\n]{0,30}(?:需要|希望)[^。！？\n]{0,30}(?:抽取|提取|摘要|分类|筛选|匹配|自动化)',re.I)


def negated(text,start):
    # Immediate grammatical prefix, not any "not" elsewhere in a paragraph.
    return bool(NEGATIVE_PREFIX.search(text[max(0,start-70):start]))


def first_asserted(text,pattern):
    return next((m for m in re.finditer(pattern,text,re.I) if not negated(text,m.start())),None)


def speculative(text,start):
    """Only an immediate tentative prefix; not a paragraph-wide rejection."""
    return bool(SPECULATIVE_PREFIX.search(text[max(0,start-70):start]))


def asserted_need(text,match):
    return not negated(text,match.start()) and not speculative(text,match.start()) and not dependency_reference(text,match)


def dependency_reference(text,match):
    # "Needs 18." is a dependency. "Needs 20 meeting reports" is not.
    return DEPENDENCY_REFERENCE.match(text[match.end():])


def span(match):
    return {'start':match.start(),'end':match.end(),'text':match.group()} if match else None


def tutorial_status(text):
    cue=next((m for m in TUTORIAL.finditer(text) if not negated(text,m.start())),None)
    problem=PERSONAL_PROBLEM.search(text)
    return {'exclude':bool(cue and not problem),'cue':span(cue),'personal_problem':span(problem),
            'note':'教程自述且无第一人称实际困难时排除；异常表达规则仍可能误判，非完整语义理解'}


def job_posting_status(title,text):
    """Require structured hiring cues, not just a job/recruiting word."""
    cues={key:span(re.search(pattern,text,re.I)) for key,pattern in JOB_SIGNALS.items()}
    scanner=re.search(r'\b(?:scan result|job posting|job listing)\b|招聘信息|职位信息',title,re.I)
    user_task=PERSONAL_PROBLEM.search(text) or USER_PROCESSING_TASK.search(text)
    hiring=bool(cues['position'] and (cues['application'] or cues['listing'] or scanner))
    return {'exclude':hiring and not bool(user_task),'signals':cues,'title_cue':span(scanner),
            'user_task':span(user_task),'note':'结构化招聘线索用于排除岗位广告；用户招聘业务处理需求不一概排除，词法规则仍可能误判'}


def compilation_status(title,text):
    """Content role is independent of the transport platform (e.g. GitHub)."""
    patterns={'paper_title':r'\bTitle\s*:', 'authors':r'\bAuthors\s*:',
              'subjects':r'\bSubjects\s*:', 'paper_link':r'\b(?:Arxiv|Pdf)\s+link\s*:',
              'abstract':r'\bAbstract\b', 'list_item':r'(?:^|\s)-\s+\[',
              'feed_summary':r'\b(?:feed items?|source changes?|source monitor)\b|安全资讯|新闻汇总'}
    signals={}
    for key,pattern in patterns.items():
        matches=list(re.finditer(pattern,text,re.I))
        signals[key]={'count':len(matches),'first':span(matches[0]) if matches else None}
    paper_digest=(all(signals[k]['count']>=2 for k in ('authors','abstract')) and
                  any(signals[k]['count']>=2 for k in ('paper_title','subjects','paper_link')))
    title_cue=re.search(r'^(?:\[?每日(?:信息流|资讯)|\[?每周资讯|weekly monitor\b|weekly source monitor\b|news digest\b|daily news\b)',title,re.I)
    news_digest=bool(title_cue and (signals['list_item']['count']>=5 or signals['feed_summary']['count']>=1))
    request_title=re.search(r'^(?:how\b|can\b|could\b|need\b|help\b|求助|如何|需要)',title,re.I)
    # A user's question may include multiple papers as supplied context.
    user_request=bool(request_title and (PERSONAL_PROBLEM.search(text) or USER_PROCESSING_TASK.search(text)))
    role='academic_compilation' if paper_digest else 'news_compilation' if news_digest else 'unclassified'
    return {'role':role,'exclude':role!='unclassified' and not user_request,
            'signals':signals,'title_cue':span(title_cue),'request_title':span(request_title),
            'user_request_exception':user_request,
            'note':'文献/资讯汇编作为背景保留，不将其转述自动算作用户需求；角色由内容规则推断，复杂混合内容仍可能误判'}
