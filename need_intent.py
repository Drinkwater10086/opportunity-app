"""Separate a desired application task from refusal, risk and completed workflows."""
import re
import context_rules

VERSION = 'unresolved-task-intent-v1'
UNMET_PATTERN = r"\b(?:I|we|our team|my team)\s+(?:still\s+)?(?:haven['’]t found|have not found|haven['’]t been able|cannot|can['’]t|struggl\w*)\b|(?:我们|我|团队)(?:仍然|目前|还)?(?:未找到|找不到|无法|难以)"
REQUEST = re.compile(r'(?:^|[.!?。！？\n])\s*(?:\b(?:how (?:can|do|should|to)|can (?:anyone|someone)|does anyone know|(?:I|we|our team|my team)\s+(?:(?:still|currently|really)\s+)*(?:needs?|want|is looking for|are looking for)|needs?)\b|求助|求推荐|有没有|我们需要|我需要|团队需要|如何)', re.I)
UNMET = re.compile(UNMET_PATTERN, re.I)
DECLINED = re.compile(r'\b(?:turn off|disable|stop using|opt out of)\s+(?:(?:all|the|an?|everyone[’\x27]s)\s+)*(?:AI|LLM|automatic transcription|meeting record\w*)\b|(?:关闭|停用|不要使用|退出)(?:所有|这个)?(?:AI|人工智能|自动转写|会议录制)', re.I)
RESOLVED = re.compile(r'\b(?:has|have)\s+(?:already\s+)?had\b[^.!?\n]{0,80}\bfor years\b|\b(?:already solved|works well|gone now|no longer (?:needed|manual))\b|(?:已解决|已经解决|不再需要人工)', re.I)
EXISTING = re.compile(r'\b(?:I (?:currently )?use|we (?:currently )?use|my routine|our current stack)\b|(?:我目前使用|我们现用)', re.I)
RISK = re.compile(r'\b(?:prompt injections?|data (?:leak\w*|exfiltration)|leak data|stolen data)\b|提示注入|数据泄露|窃取数据', re.I)
MITIGATION = re.compile(r'\b(?:detect|prevent|block|filter|redact|monitor|protect)\w*\b|检测|防护|阻止|过滤|脱敏', re.I)
SPECULATIVE = re.compile(r'\b(?:what this might look like|one could imagine|perhaps (?:AI|a model)|AI might someday)\b|(?:设想|也许可以|或许可以|未来可能)', re.I)
CONSISTENCY = re.compile(r'\b(?:idempotenc\w*|idempotent|unique constraints?|concurrent executions)\b|幂等|唯一约束|并发执行', re.I)
DUPLICATES = re.compile(r'\bduplicate (?:records?|contacts?|requests?)\b|重复记录|重复联系人|重复请求', re.I)
ENTITY_AMBIGUITY = re.compile(r'\b(?:entity resolution|fuzzy match\w*|semantic (?:match\w*|similarity)|name variants|aliases)\b|实体消歧|模糊匹配|语义匹配|姓名变体', re.I)
PRIVATE_ALTERNATIVE = re.compile(r'\b(?:local|private|offline)\b[^.!?\n]{0,120}\b(?:AI|Whisper|transcription)\b|\b(?:AI|Whisper|transcription)\b[^.!?\n]{0,120}\b(?:locally|offline)\b|本地AI|离线转写', re.I)
GOAL_FUNCTIONS = (
    ('审核审查', r'\b(?:detect|prevent|block|filter|monitor)\w*\b[^.!?\n]{0,60}\b(?:prompt injections?|data leak\w*)\b|检测提示注入|防止数据泄露'),
    ('知识检索', r'(?:stor\w* and quer\w*|quer\w*|search\w*|retriev\w*)[^.!?\n]{0,60}\bknowledge\b|知识(?:存储|查询|检索)|知识库'),
    ('图像识别', r'\b(?:OCR|scanned|PDF|invoice)\b[^.!?\n]{0,100}\b(?:extract\w*|recogn\w*)\b|\bextract\w*\b[^.!?\n]{0,100}\b(?:PDF|invoice)\b|发票识别|图像识别'),
    ('语音处理', r'\b(?:meeting transcription|speech recognition|transcrib\w*|audio)\b|会议转写|语音识别'),
    ('自动化流程', r'\b(?:workflow|CRM|automat\w*)\b|工作流|自动化流程'),
)


def inspect(text):
    request = REQUEST.search(text)
    unmet = UNMET.search(text)
    open_task = bool(request or unmet)
    matches = {key: pattern.search(text) for key, pattern in (
        ('declined_ai', DECLINED), ('resolved', RESOLVED), ('existing', EXISTING),
        ('risk', RISK), ('speculative', SPECULATIVE), ('consistency', CONSISTENCY))}
    reason = None
    if matches['declined_ai'] and not (request and PRIVATE_ALTERNATIVE.search(text)):
        reason = 'declined_ai'
    elif matches['consistency'] and DUPLICATES.search(text) and not ENTITY_AMBIGUITY.search(text):
        reason = 'engineering_consistency'
    elif matches['risk'] and not (open_task and MITIGATION.search(text)):
        reason = 'risk_without_application_request'
    elif matches['speculative'] and not open_task:
        reason = 'speculative_application'
    elif (matches['resolved'] or matches['existing']) and not open_task:
        reason = 'resolved_application'
    goal = unmet or request
    goal_span = None
    function = None
    if goal:
        start = goal.start()
        while start < len(text) and (text[start].isspace() or text[start] in '.!?。！？'):
            start += 1
        ending = re.search(r'[.!?。！？\n]', text[goal.end():])
        end = goal.end()+ending.end() if ending else len(text)
        goal_span = {'start': start, 'end': end, 'text': text[start:end]}
        for label, pattern in GOAL_FUNCTIONS:
            if re.search(pattern, goal_span['text'], re.I):
                function = label
                break
    return {'version': VERSION, 'exclude': reason is not None, 'reason': reason,
            'open_task': open_task, 'goal': goal_span, 'goal_function': function,
            'signals': {key: context_rules.span(match) for key, match in matches.items()},
            'unresolved': context_rules.span(unmet), 'request': context_rules.span(request)}
