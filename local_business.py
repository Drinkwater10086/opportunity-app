"""Business-task evidence and source-linked theme briefs."""
import re
import context_rules

VERSION='business-task-evidence-v1'
TECHNICAL_INCIDENT=r'\b(?:HTTP\s*[45]\d\d|traceback|stack trace|importerror|modulenotfounderror|segmentation fault|connection refused|API (?:key|authentication|rate limit|timeout)|dependency conflict|build fails?|pip install)\b|接口报错|依赖冲突|安装失败|编译失败|密钥无效|连接超时'
TASK=(r'会议(?:转写|纪要)|发票(?:识别|抽取)|合同(?:审查|审核)|'
      r'\b(?:meeting transcription|speech recognition|sentiment analysis|intent classification)\b|'
      r'(?:提取|抽取|转写|总结|分类|审核|审查|翻译|推荐|预测|识别|自动回复)[^。！？\n]{0,60}(?:邮件|会议|文档|合同|发票|客户|报告|知识库|用户|订单)|'
      r'\b(?:extract\w*|transcrib\w*|summariz\w*|classif\w*|translat\w*|recommend\w*|predict\w*|recogniz\w*|automate|process)\b'
      r'[^.!?\n]{0,90}\b(?:emails?|meetings?|documents?|contracts?|invoices?|customers?|reports?|knowledge base|users?|orders?|transcripts?)\b')
SIGNALS={
 'task':TASK,
 'existing_process':r'目前|现有流程|手工|手动|\b(?:currently|manually|manual process|existing workflow|we use|I use)\b',
 'gap':r'耗时|费时|重复录入|效率低|遗漏|重复记录|\b(?:time.consuming|duplicate records?|missing records?|repetitive|cannot|unable|struggl\w*)\b',
 'recurrence':r'每天|每周|每月|每次|批量|反复|\b(?:every day|every week|each meeting|daily|weekly|monthly|repeatedly|hundreds of)\b',
 'technical_incident':TECHNICAL_INCIDENT,
}


def sentence_excerpt(text,start,end):
    separators=list(re.finditer(r'[。！？!?\n]|\.(?=\s|$)',text))
    lo=max([match.end() for match in separators if match.end()<=start]+[0])
    hi=min([match.end() for match in separators if match.start()>=end]+[len(text)])
    while lo<hi and text[lo].isspace():lo+=1
    while hi>lo and text[hi-1].isspace():hi-=1
    return {'start':lo,'end':hi,'text':text[lo:hi]}


def inspect(text):
    signals={}
    for key,pattern in SIGNALS.items():
        match=context_rules.first_asserted(text,pattern)
        if not match:
            signals[key]=None
            continue
        signals[key]={**sentence_excerpt(text,match.start(),match.end()),'cue':match.group()}
    incident=bool(signals['technical_incident'] and not signals['task'])
    return {'version':VERSION,'signals':signals,'technical_only':incident,
            'role':'technical_incident' if incident else 'business_task' if signals['task'] else 'general_request'}


def theme_brief(cluster,judgments):
    members=cluster['records']
    ordered=([cluster['representative_id']] if cluster.get('representative_id') in members else [])+[rid for rid in members if rid!=cluster.get('representative_id')]
    def snippets(field):
        found=[]
        for rid in ordered:
            j=judgments[rid]
            if field in ('need','context','feasible'):
                span=j['evidence_spans'].get(field)
                context=j.get('selected_context')
                if span and context:
                    excerpt=sentence_excerpt(context['text'],span.get('match_start',span['start'])-context['start'],span.get('match_end',span['end'])-context['start'])
                    choices=[{**excerpt,'start':excerpt['start']+context['start'],'end':excerpt['end']+context['start']}]
                else:choices=[{'start':span['start'],'end':span['end'],'text':span['text']}] if span else []
            else:
                choices=[entry['signals'].get(field) for entry in j.get('business_contexts',[]) if entry['signals'].get(field)]
            for span in choices:
                if any(e['record_id']==rid and e['start']==span['start'] for e in found):continue
                stop=min(span['end'],span['start']+350)
                found.append({'record_id':rid,'start':span['start'],'end':stop,'text':span['text'][:stop-span['start']],'truncated':stop<span['end']})
                if len(found)==3:return found
        return found
    return {'version':VERSION,'users':snippets('context'),'problems':snippets('need'),
            'current_process':snippets('existing_process'),'gaps':snippets('gap'),
            'recurrence':snippets('recurrence'),'technical_basis':snippets('feasible'),
            'record_count':len(members),'platform_count':len(cluster['sources']),
            'next_step':'核对现有处理流程，选取典型输入验证核心功能，并据此完善立项策划。'}
