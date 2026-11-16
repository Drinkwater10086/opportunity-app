"""Offline, versioned research baseline. No network/model-provider calls.

Rules are engineering hypotheses, not ground truth or calibrated probabilities.
LSA is corpus-local latent semantics, not a pretrained multilingual encoder.
"""
import hashlib
import json
import re
import math
import sys
import local_preprocessing as preprocessing
import local_embeddings
import evidence_scoring
import context_rules
import local_value
from bisect import bisect_left
from collections import Counter

import numpy as np
import sklearn
from sklearn.cluster import AgglomerativeClustering
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.metrics.pairwise import cosine_distances
from sklearn.preprocessing import normalize

from analysis_engine import FUNCTIONS, INDUSTRIES, rank_clusters

VERSION = 'local-rules-v19-program-release'
SEED = 42
MAX_RECORDS = 5000
MAX_CHARACTERS = 20_000_000
MAX_CANDIDATES = 2000
FUNCTION_TERMS = dict(zip(FUNCTIONS, [
    '图像识别,图像检测,image recognition,object detection,ocr',
    '语义分析,意图识别,sentiment,intent classification,text classification',
    '语音处理,语音识别,speech recognition,transcription,whisper',
    '文本生成,写作,text generation,writing,drafting,summarization,summarize,摘要',
    '对话问答,聊天,chatbot,question answering,chat assistant',
    '推荐系统,recommendation system,recommender',
    '知识检索,知识库,knowledge base,retrieval,rag',
    '数据挖掘,数据抽取,data mining,extraction,extract',
    '多模态,multimodal,vision language',
    '智能体,agent,orchestration',
    '自动化,工作流,automation,workflow,automate',
    '预测,forecast,prediction,predictive',
    '审核,审查,合规,audit,compliance,moderation',
    '搜索,匹配,search,matching',
    '翻译,转写,translation,translate,transcribe',
    '视频理解,video understanding,video analysis',
]))
INDUSTRY_TERMS = dict(zip(INDUSTRIES, [
    '金融,银行,finance,banking', '教育,教学,education,teacher,student',
    '医疗,患者,healthcare,medical,patient', '法律,律师,legal,lawyer',
    '电商,ecommerce,e-commerce,online store', '零售,retail',
    '房地产,real estate', '制造,manufacturing,factory', '物流,logistics,warehouse',
    '游戏,gaming,game', '餐饮,restaurant', '农业,agriculture,farming',
    '政务,government', '汽车,automotive', '家居,smart home',
    '交通,transportation,road traffic', '能源,energy', '通信,telecom',
    '娱乐,entertainment', '体育,sports', '旅游,tourism,travel',
    '保险,insurance', '建筑,construction', '环保,environmental',
    '科研,research,scientific', '人力资源,招聘,human resources,recruiting',
    '媒体出版,新闻,publishing,journalism,news', '营销广告,marketing,advertising',
    '外贸,foreign trade,international trade', '',
]))
OFFICE = '会议,邮件,审批,合同,办公,销售,人事,财务,meeting,meetings,email,emails,approval,approvals,contract,contracts,office,offices,knowledge base,knowledge bases,sales,crm,human resources,invoice,invoices,payroll'
PATTERNS = {
    'need': r'有没有|求推荐|求助|需要|希望|耗时|费时|手动|无法|困难|痛点|重复录入|效率低|\b(?:needs?|needed|looking for|struggl\w*|manual(?:ly)?|time.consuming|cannot|can.t|unable|problem|feature request|how (?:can|do|to))\b',
    'ai': r'人工智能|大模型|语言模型|机器学习|语音识别|图像识别|(?<![A-Za-z0-9_])(?:AI|LLMs?|GPT[A-Za-z0-9]*|machine learning|Whisper|OCR|RAG|neural|language model)(?![A-Za-z0-9_])',
    'feasible': r'模型|识别|检索|转写|分类|预测|抽取|\b(?:API|model|OCR|Whisper|retrieval|transcri\w*|classif\w*|extract\w*|predict\w*)\b',
    'context': r'用户|员工|客户|团队|会议|文档|邮件|合同|报表|流程|患者|学生|教师|\b(?:users?|employees?|customers?|teams?|meetings?|documents?|emails?|contracts?|reports?|workflow|patients?|students?|teachers?|invoices?)\b',
    'exclude': r'购买链接|限时优惠|\b(?:sponsored|buy now|limited.time offer|affiliate link)\b',
    'negated_ai': r'不(?:需要|使用|用)\s*(?:AI|人工智能|大模型)|\b(?:without|no need for|do not (?:use|need)|don.t (?:use|need))\s+(?:an?\s+)?(?:AI|LLM|GPT|machine learning)\b',
}


def terms(text):
    return [s.strip() for s in re.split(r'[,，;；\n]', text) if s.strip()]


def contains(text, term):
    # ASCII word boundaries prevent AI matching "email" or RAG matching "storage".
    return re.search(evidence_scoring.term_pattern(term), text, re.I) is not None


def direction_scope(direction,config):
    explicit=terms(config.get('direction_terms',''))
    if explicit:
        return {'mode':'explicit','profile':None,'configured_terms':list(dict.fromkeys(explicit)),
                'expanded_terms':[],'note':'仅使用显式方向词，不另加办公或行业扩展'}
    def normalize(value):
        value=re.sub(r'人工智能|智能|应用|场景|行业|方向|企业|自动化','',value,flags=re.I)
        value=re.sub(r'(?<![a-z0-9_])(?:AI|applications?|industry|scenarios?|enterprise|automation)(?![a-z0-9_])','',value,flags=re.I)
        return re.sub(r'[\s:：,，;；/]+','',value).casefold()
    requested=terms(direction);normalized=normalize(direction)
    if normalized in ('办公','office'):
        return {'mode':'office_profile','profile':'办公','configured_terms':requested,
                'expanded_terms':terms(OFFICE),'normalized_direction':normalized,
                'note':'已识别通用办公方向，使用声明的中英场景词；额外限定词不会自动丢弃'}
    for name,words in INDUSTRY_TERMS.items():
        aliases=terms(words)
        if aliases and normalized and normalized in {normalize(v) for v in [name]+aliases}:
            return {'mode':'industry_profile','profile':name,'configured_terms':requested,
                    'expanded_terms':list(dict.fromkeys([name]+aliases)),'normalized_direction':normalized,
                    'note':'仅在规范化方向完整匹配已知行业名称或别名时扩展，不是自由语义推断'}
    return {'mode':'literal','profile':None,'configured_terms':requested,'expanded_terms':[],
            'normalized_direction':normalized,'note':'方向未完整匹配已知画像，保留原方向词，可显式提供中英检索方向词'}


def evidence(text, pattern):
    match = re.search(pattern, text, re.I)
    return match_evidence(text,match)


def match_evidence(text,match):
    if not match:
        return None
    start, end = max(0, match.start()-80), min(len(text), match.end()+120)
    return {'start': start, 'end': end, 'text': text[start:end],
            'match_start': match.start(), 'match_end': match.end(), 'match': match.group()}


def nearby_evidence(text):
    """Inspect all matches, including late passages in long documents."""
    needs = [m for m in re.finditer(PATTERNS['need'], text, re.I) if context_rules.asserted_need(text,m)]
    ai_matches = list(re.finditer(PATTERNS['ai'], text, re.I))
    positions=[m.start() for m in ai_matches]
    best=None
    for need in needs:
        j=bisect_left(positions,need.start())
        nearest=min((i for i in (j-1,j) if 0<=i<len(ai_matches)),key=lambda i:abs(ai_matches[i].start()-need.start()),default=None)
        if nearest is not None and abs(ai_matches[nearest].start()-need.start()) <= 600:
            ai=ai_matches[nearest]
            spans = []
            for match in (need, ai):
                start, end = max(0, match.start()-80), min(len(text), match.end()+120)
                spans.append({'start':start,'end':end,'text':text[start:end],
                              'match_start':match.start(),'match_end':match.end(),'match':match.group()})
            rank=(evidence_scoring.need_signal(need.group())[0],-abs(ai.start()-need.start()),-need.start())
            if best is None or rank>best[0]:best=(rank,spans)
    return best[1] if best else None


def label(text, dictionary, default):
    scores = {name: sum(contains(text, t) for t in terms(words)) for name, words in dictionary.items()}
    best = max(scores, key=scores.get)
    return (best if scores[best] else default), scores


def judge_window(record, direction, config):
    text = record['content']
    hits = {key: evidence(text, pattern) for key, pattern in PATTERNS.items()}
    denied_needs=[context_rules.span(m) for m in re.finditer(PATTERNS['need'],text,re.I) if context_rules.negated(text,m.start())]
    tentative_needs=[context_rules.span(m) for m in re.finditer(PATTERNS['need'],text,re.I) if context_rules.speculative(text,m.start())]
    hits['need']=match_evidence(text,next((m for m in re.finditer(PATTERNS['need'],text,re.I) if context_rules.asserted_need(text,m)),None))
    hits['exclude']=match_evidence(text,context_rules.first_asserted(text,PATTERNS['exclude']))
    tutorial=context_rules.tutorial_status(text)
    job_posting=record.get('_job_posting') or context_rules.job_posting_status(record.get('title',''),text)
    compilation=record.get('_compilation') or context_rules.compilation_status(record.get('title',''),text)
    showcase=record.get('_showcase') or context_rules.showcase_status(record.get('title',''),text)
    paired = nearby_evidence(text)
    if paired:
        hits['need'], hits['ai'] = paired
    scope_definition=record.get('_direction_scope') or direction_scope(direction,config)
    direct_scope_hits=[term for term in scope_definition['configured_terms'] if contains(text,term)]
    scope=list(dict.fromkeys(scope_definition['configured_terms']+scope_definition['expanded_terms']))
    scope_hits = [term for term in scope if contains(text, term)]
    function, function_scores = label(text, FUNCTION_TERMS, '')
    industry, industry_scores = label(text, INDUSTRY_TERMS, '其他')
    quality = len(text.strip()) >= 30
    supporting_only = record.get('metadata', {}).get('provenance', {}).get('evidence_role') == 'technical_context'
    # Co-occurrence is a proxy only; it cannot prove AI is necessary to solve the need.
    related_ai = bool(paired and not hits['negated_ai'])
    checks = {'quality': quality, 'relevant': bool(scope_hits), 'real_need': bool(hits['need']),
              'context': bool(hits['context']), 'ai_core': related_ai,
              'feasible': bool(hits['feasible']), 'classified': bool(function)}
    score,score_detail=evidence_scoring.strength(text,checks,hits,direct_scope_hits,scope_hits)
    score_detail['components']['classified']['matched_terms']=[term for term in terms(FUNCTION_TERMS.get(function,'')) if contains(text,term)]
    score_detail['raw_evidence_score']=score
    score_detail['selected_method']=config.get('score_method','evidence_strength')
    if config.get('score_method','evidence_strength')=='completeness':score=score_detail['completeness']
    excluded = bool(hits['exclude']) or supporting_only or tutorial['exclude'] or job_posting['exclude'] or compilation['exclude'] or showcase['exclude']
    score_detail['raw_selected_score']=score
    if config.get('score_method','evidence_strength')=='evidence_strength':
        cap=.2 if excluded else .49 if not all(checks.values()) else 1.
        score=min(score,cap)
        score_detail['score_cap']=cap
        score_detail['cap_reason']='排除情形上限0.2' if excluded else '缺少硬条件上限0.49' if cap<1 else '硬条件完整，不附加限分'
    score_detail['final_score']=score
    opportunity = int(all(checks.values()) and not excluded and score >= config['threshold'])
    hard_failures = [key for key, passed in checks.items() if not passed] + (['exclude'] if hits['exclude'] else []) + (['tutorial_content'] if tutorial['exclude'] else []) + (['job_posting'] if job_posting['exclude'] else []) + (['technical_context_only'] if supporting_only else [])
    if compilation['exclude']:hard_failures.append('compiled_background')
    if showcase['exclude']:hard_failures.append('solution_showcase')
    failures=hard_failures+(['below_threshold'] if score<config['threshold'] else [])
    def quote(key):
        return hits[key]['text'] if hits[key] else ''
    return {**checks, 'opportunity': opportunity, 'excluded': excluded, 'confidence': score,
            'score_kind': '启发式证据强度，非校准概率' if config.get('score_method','evidence_strength')=='evidence_strength' else '旧版条件完整性分数，非校准概率',
            'score_detail':score_detail,'rule_completeness':score_detail['completeness'],
            'content_context':{'version':context_rules.VERSION,'denied_need_spans':denied_needs,'tentative_need_spans':tentative_needs,'tutorial':tutorial},
            'gate_passed':not hard_failures,'hard_gate_failures':hard_failures,
            'function': function if opportunity else '', 'industry': industry if opportunity else '',
            'label_scores': {'function': function_scores, 'industry': industry_scores},
            'scope_terms': scope_hits,'direction_scope':scope_definition, 'evidence_spans': hits, 'failed_checks': failures,
            'reason': '硬条件及证据评分阈值通过，仍需验证语义正确性' if opportunity else '未通过：'+', '.join(failures),
            'pain': quote('need'), 'target_user': quote('context'), 'evidence': quote('need'),
            'need_evidence': quote('need'), 'user_evidence': quote('context'),
            'ai_evidence': quote('ai'), 'feasibility_evidence': quote('feasible'),
            'need_kind': score_detail['need_kind'],
            'relevant_evidence': scope_hits}


def judge(record, direction, config):
    original = record['content']
    structured = preprocessing.structure(original)
    # Genre cues may sit outside the selected demand window. Keep source offsets
    # in the full masked record; do not reinterpret title offsets as body offsets.
    record={**record,'_job_posting':context_rules.job_posting_status(record.get('title',''),structured['text'])}
    record['_compilation']=context_rules.compilation_status(record.get('title',''),structured['text'])
    record['_showcase']=context_rules.showcase_status(record.get('title',''),structured['text'])
    record['_direction_scope']=direction_scope(direction,config)
    candidates = []
    fallback = None
    for start, end, window in preprocessing.windows(structured):
        # Cheap prefilter: at least a demand/AI/context signal before dictionary evaluation.
        if not re.search(PATTERNS['need'], window, re.I):
            continue
        signals = sum(bool(re.search(PATTERNS[key], window, re.I)) for key in ('ai','context','feasible'))
        if fallback is None or signals > fallback[0]:
            fallback = (signals, start, end, window)
        if signals < 3:
            continue
        result = judge_window({**record, 'content': window}, direction, config)
        candidates.append((int(result['gate_passed']), result['confidence'], -start, start, end, result))
        if config.get('score_method')=='completeness' and result['gate_passed']:
            break
    if not candidates and fallback:
        _, start, end, window = fallback
        result = judge_window({**record, 'content': window}, direction, config)
        candidates.append((int(result['gate_passed']), result['confidence'], -start, start, end, result))
    if candidates:
        _, _, _, start, end, result = max(candidates, key=lambda x:x[:3])
    else:
        start, end, window = next(preprocessing.windows(structured),(0,0,''))
        result = judge_window({**record, 'content': window}, direction, config)
    for span in result['evidence_spans'].values():
        if span:
            for field in ('start','end','match_start','match_end'): span[field] += start
            span['text'] = original[span['start']:span['end']]
            span['match'] = original[span['match_start']:span['match_end']]
    for component in result['score_detail']['components'].values():
        for span in component['evidence']:
            span['start']+=start;span['end']+=start
            span['text']=original[span['start']:span['end']]
    context=result['content_context']
    context['job_posting']=record['_job_posting']
    context['compilation']=record['_compilation']
    context['showcase']=record['_showcase']
    for span in context['denied_need_spans']+context['tentative_need_spans']+[s for s in (context['tutorial']['cue'],context['tutorial']['personal_problem']) if s]:
        span['start']+=start;span['end']+=start;span['text']=original[span['start']:span['end']]
    # Selection may move to another window after removing a tentative match.
    # Keep record-wide cues so the reason for that change stays inspectable.
    context['record_tentative_need_spans']=[
        {'start':m.start(),'end':m.end(),'text':original[m.start():m.end()],
         'prefix_start':max(0,m.start()-70),'prefix_text':original[max(0,m.start()-70):m.start()]}
        for m in re.finditer(PATTERNS['need'],structured['text'],re.I)
        if context_rules.speculative(structured['text'],m.start())]
    context['record_dependency_need_spans']=[]
    for match in re.finditer(PATTERNS['need'],structured['text'],re.I):
        reference=context_rules.dependency_reference(structured['text'],match)
        if reference:
            reference_end=match.end()+reference.end()
            context['record_dependency_need_spans'].append({'start':match.start(),'end':reference_end,'text':original[match.start():reference_end]})
    for target, source in [('evidence','need'),('need_evidence','need'),('pain','need'),
                           ('user_evidence','context'),('target_user','context'),
                           ('ai_evidence','ai'),('feasibility_evidence','feasible')]:
        span=result['evidence_spans'][source]
        result[target]=span['text'] if span else ''
    result['selected_context']={'start':start,'end':end,'text':original[start:end],
                                'method':'同结构单元最多3个相邻句；不跨列表项/标题/表格行；上下文最长1200字符；超长单句全覆盖分片，无截断'}
    result['analysis_text']=structured['text'][start:end]
    result['preprocessing']={k:v for k,v in structured.items() if k!='text'}
    result['evidence_sufficiency']={key:bool(result['evidence_spans'][key]) for key in ('need','context','ai','feasible')}
    result['data_quality']=structured['quality']
    return result


def partition(distances, threshold):
    if len(distances) < 2:
        return np.zeros(len(distances), dtype=int)
    return AgglomerativeClustering(n_clusters=None, metric='precomputed', linkage='average',
                                  distance_threshold=threshold).fit_predict(distances)


def diagnostic(distances, labels):
    counts = Counter(int(x) for x in labels)
    n = len(labels)
    score, reason = None, '需要至少两个簇，且簇数小于样本数'
    if 1 < len(counts) < n:
        if np.max(distances) <= 1e-12:
            reason = '向量相同，不能评价区分度'
        else:
            score = float(silhouette_score(distances, labels, metric='precomputed'))
            reason = '内部几何指标，不是准确率，也不证明业务语义正确'
    warnings=[]
    if n>=2 and len(counts)==1:warnings.append('全部候选被合为一个簇，无法证明主题区分能力')
    if n>=3 and max(counts.values(),default=0)/n>.8:warnings.append('最大簇超过80%，可能存在过度合并')
    if n>=3 and sum(v==1 for v in counts.values())/n>.5:warnings.append('超过半数候选各成单簇，可能存在过度拆分')
    return {'sample_count': n, 'cluster_count': len(counts), 'silhouette': score, 'reason': reason,'warnings':warnings,
            'singleton_count': sum(v == 1 for v in counts.values()),
            'singleton_fraction': sum(v == 1 for v in counts.values()) / max(n, 1),
            'largest_cluster_fraction': max(counts.values(), default=0) / max(n, 1)}


def distances_for(vectors):
    d = cosine_distances(vectors)
    d = np.clip((d + d.T)/2, 0, 2)
    np.fill_diagonal(d, 0)
    return d


def topic_keywords(members):
    """Extract corpus terms. Each term has a recorded source; no generated evidence."""
    stops = set('the and for with this that from have has are was were will would could should need needs using use used our their your can not how what when which into about model api team comments comment full issue issues github readme code example examples response token usage integration support please version also more some any all but its they them these those been being'.split())
    candidate_terms = set()
    for r in members:
        candidate_terms.update(w.lower() for w in re.findall(r'\b[A-Za-z][A-Za-z-]{2,}\b', r['content']) if w.lower() not in stops)
    for dictionary in (FUNCTION_TERMS, INDUSTRY_TERMS):
        candidate_terms.update(t for words in dictionary.values() for t in terms(words) if not t.isascii())
    candidate_terms.update(t for t in terms(OFFICE) if not t.isascii())
    ranked = []
    for term in sorted(candidate_terms):
        supporters = [r['id'] for r in members if contains(r['content'], term)]
        title_hits = sum(contains(r['title'], term) for r in members)
        if supporters:
            ranked.append((len(supporters)+2*title_hits, term, supporters))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    return [{'term':t,'record_ids':ids} for _,t,ids in ranked[:3]]


SCENARIO_TERMS={
    '会议':'会议,meeting,meetings','邮件':'邮件,email,emails',
    '合同':'合同,contract,contracts','发票':'发票,invoice,invoices',
    '审批':'审批,approval,approvals','知识库':'知识库,knowledge base,knowledge bases',
    'CRM':'CRM','人事':'人事,human resources','薪酬':'薪酬,payroll',
    '销售':'销售,sales','报告':'报告,report,reports','报表':'报表,report table,report tables','文档':'文档,document,documents',
    'PDF':'PDF,PDFs','办公':'办公,office,offices',
}


def topic_name(members, representative, keywords, function,judgments=None):
    """Template summary from majority-supported source concepts; no generation."""
    features=[]
    for label,words in SCENARIO_TERMS.items():
        evidence=[]
        for record in members:
            j=(judgments or {}).get(record['id'])
            text=j['analysis_text'] if j else record['content']
            offset=j['selected_context']['start'] if j else 0
            hits=[]
            for term in terms(words):
                pattern=re.escape(term)
                if term.isascii():pattern=r'(?<![A-Za-z0-9_])'+pattern+r'(?![A-Za-z0-9_])'
                hit=re.search(pattern,text,re.I)
                if hit:hits.append(hit)
            if hits:
                hit=min(hits,key=lambda m:(m.start(),-len(m.group())))
                start,end=offset+hit.start(),offset+hit.end()
                evidence.append({'record_id':record['id'],'field':'content','start':start,'end':end,
                                 'text':record['content'][start:end]})
        if len(evidence)>len(members)/2:
            features.append({'label':label,'support_count':len(evidence),'record_count':len(members),'evidence':evidence})
    features.sort(key=lambda f:(-f['support_count'],min(e['start'] for e in f['evidence']),f['label']))
    if len(features)>1:features=[f for f in features if f['label']!='办公']
    if features:
        chosen=features[:2]
        return {'name':'、'.join(f['label'] for f in chosen)+'场景的'+function+'候选需求',
                'name_method':'固定中英场景词典映射，场景词须出现于超过半数成员的判别上下文；结合功能标签形成句式，不推断方向关系，未验证共同需求正确性',
                'name_features':chosen,'name_evidence':None}
    if len(members)==1:
        field='title' if representative['title'].strip() else 'content'
        text=representative[field]
        excerpt=text[:180]
        return {'name':('原文标题：' if field=='title' else '原文节选：')+excerpt+('…' if len(text)>180 else ''),
                'name_method':'单记录主题直接展示原文标题或正文节选，不能证明跨记录共同需求',
                'name_features':[],
                'name_evidence':{'record_id':representative['id'],'field':field,'start':0,'end':len(excerpt),'text':excerpt}}
    title='、'.join(k['term'] for k in keywords)
    return {'name':f'围绕{title[:60]}的{function}需求' if title else representative['title'][:90] or representative['content'][:90],
            'name_method':'多记录主题按原文关键词与功能标签组成固定句式，须核对各成员；关键词可能含泛词',
            'name_features':[],'name_evidence':None}


def screening_flow(judgments,threshold):
    """Disjoint removals in a declared display order, not a new classifier."""
    remaining=set(judgments)
    labels=[('quality','正文质量'),('relevant','研究方向相关性'),('real_need','肯定需求线索'),
            ('context','用户或使用场景'),('ai_core','AI与需求关联'),('feasible','技术实现线索'),
            ('classified','功能分类'),('not_excluded','内容类型排除'),('threshold','证据分阈值')]
    stages=[]
    for key,label in labels:
        def passed(j):
            if key=='not_excluded':return not j['excluded']
            if key=='threshold':return j['confidence']>=threshold
            return bool(j[key])
        removed=sorted(rid for rid in remaining if not passed(judgments[rid]))
        entered=len(remaining);remaining.difference_update(removed)
        stages.append({'key':key,'label':label,'entered':entered,'removed':len(removed),
                       'remaining':len(remaining),'removed_ids':removed})
    return {'stages':stages,'record_count':len(judgments),'final_ids':sorted(remaining),
            'matches_decisions':remaining=={rid for rid,j in judgments.items() if j['opportunity']},
            'note':'按固定展示顺序累计筛选，各条记录只计入首次流失环节；其他不通过条件可能重叠。顺序不改变判别规则或结果。'}


def analyze(batch, records, config, source_count):
    records = sorted(records, key=lambda r: r['id'])
    if len(records) > MAX_RECORDS or sum(len(r['content']) for r in records) > MAX_CHARACTERS:
        raise ValueError('超出本地保护范围：最多5000条、合计2000万字符；未截断数据')
    judgments = {r['id']: judge(r, batch['direction'], config) for r in records}
    positives = [r for r in records if judgments[r['id']]['opportunity']]
    if len(positives) > MAX_CANDIDATES:
        raise ValueError('候选超过2000条，层次聚类距离矩阵超出保护范围；未静默抽样')
    empty = diagnostic(np.zeros((0, 0)), [])
    evaluation = {'primary': empty, 'baseline': empty, 'sensitivity': [],
                  'threshold_sensitivity': [{'threshold': t, 'candidate_count': sum(
                      j['gate_passed'] and j['confidence'] >= t for j in judgments.values())}
                      for t in sorted({.5, .6, .7, .75, .8, .85, .9, .95, config['threshold']})],
                  'ablation': {key: sum(not j['excluded'] and all(j[k] for k in
                      ('quality','relevant','real_need','context','ai_core','feasible','classified') if k != key)
                      and j['confidence'] >= config['threshold'] for j in judgments.values())
                      for key in ('relevant', 'real_need', 'ai_core', 'feasible')},
                  'note': '没有人工真值，不报告准确率或F1。ARI比较距离阈值扰动下的分组，不是独立重复运行或正确性。证据强度评分未经概率校准，阈值敏感性同时保留所有硬门槛；旧版完整性方法可能不随阈值变化。'}
    clusters, representation = [], '无候选，不构建向量'
    embedding_metadata = None
    vector_method = config.get('vector_method','lsa')
    cluster_threshold = config.get('semantic_distance_threshold',.15) if vector_method=='e5' else config['distance_threshold']
    duplicates = preprocessing.duplicate_groups([], np.zeros((0,0)))
    if positives:
        vectorizer = TfidfVectorizer(analyzer='char', ngram_range=(2, 4), max_features=20000,
                                     sublinear_tf=True, norm='l2')
        x = vectorizer.fit_transform([judgments[r['id']]['analysis_text'] for r in positives])
        if np.any(np.asarray(x.getnnz(axis=1)) == 0):
            raise ValueError('存在零向量，不能可靠聚类；未删除该记录')
        vectors = x
        # Reduction needs a meaningful smaller dimension; tiny batches stay lexical explicitly.
        dimensions = min(config['dimensions'], max(2, (len(positives)-1)//2), x.shape[1]-1)
        representation = 'TF-IDF词面向量' if vector_method=='tfidf' else 'TF-IDF（候选少于8条，未执行LSA以避免极低维度过度合并）'
        if vector_method=='e5':
            vectors, embedding_metadata = local_embeddings.embed([judgments[r['id']]['analysis_text'] for r in positives])
            representation = '本地multilingual-e5-small量化ONNX句向量（预训练语义特征）'
        elif vector_method=='lsa' and len(positives) >= 8 and dimensions >= 2:
            svd = TruncatedSVD(n_components=dimensions, random_state=SEED)
            vectors = normalize(svd.fit_transform(x))
            if np.any(np.linalg.norm(vectors, axis=1) < 1e-12):
                raise ValueError('LSA出现零向量，请调整维度；未伪造距离')
            representation = f'字符TF-IDF + LSA({dimensions}维)；语料内潜在语义，非跨语言预训练模型'
        distances = distances_for(vectors)
        baseline_distances = distances_for(x)
        original_vectors = TfidfVectorizer(analyzer='char', ngram_range=(2,4), max_features=20000, sublinear_tf=True).fit_transform([r['content'] for r in positives])
        original_distances = distances_for(original_vectors)
        duplicates = preprocessing.duplicate_groups(positives, original_distances)
        labels = partition(distances, cluster_threshold)
        base_labels = partition(baseline_distances, config['distance_threshold'])
        evaluation['primary'] = diagnostic(distances, labels)
        evaluation['baseline'] = diagnostic(baseline_distances, base_labels)
        evaluation['baseline_in_primary_space'] = diagnostic(distances, base_labels)
        evaluation['primary_in_lexical_space'] = diagnostic(original_distances, labels)
        evaluation['baseline_in_full_text_space'] = diagnostic(original_distances, base_labels)
        evaluation['baseline_labels'] = dict(zip([r['id'] for r in positives], map(int, base_labels)))
        if vector_method=='e5':
            evaluation['semantic_threshold_grid'] = [
                {'distance_threshold':threshold,**diagnostic(distances,partition(distances,threshold))}
                for threshold in (.05,.1,.15,.2,.25)]
        perturbation = .03 if vector_method=='e5' else .1
        for threshold in sorted({max(.01, cluster_threshold-perturbation), min(1.5, cluster_threshold+perturbation)}):
            other = partition(distances, threshold)
            evaluation['sensitivity'].append({'distance_threshold': threshold,
                'ari': float(adjusted_rand_score(labels, other)) if len(labels) >= 2 else None,
                **diagnostic(distances, other)})
        for group in sorted(set(labels)):
            indices = np.flatnonzero(labels == group)
            members = [positives[i] for i in indices]
            # Medoid is a real representative, never a generated claim.
            medoid = int(indices[np.argmin(distances[np.ix_(indices, indices)].mean(axis=1))])
            representative = positives[medoid]
            function = Counter(judgments[r['id']]['function'] for r in members).most_common(1)[0][0]
            industry = Counter(judgments[r['id']]['industry'] for r in members).most_common(1)[0][0]
            keywords = topic_keywords([{**r, 'content':judgments[r['id']]['analysis_text']} for r in members])
            clusters.append({**topic_name(members,representative,keywords,function,judgments),
                             'keywords': keywords,
                             'representative_id': representative['id'], 'function': function,
                             'industry': industry, 'records': [r['id'] for r in members]})
        clusters = rank_clusters(clusters, positives, source_count,
                                 (config['coverage_weight'], config['scale_weight']))
        duplicate_ids = {rid:g['representative_id'] for g in duplicates['groups'] for rid in g['records']}
        for cluster in clusters:
            cluster['unique_evidence_count'] = len({duplicate_ids.get(rid,rid) for rid in cluster['records']})
            cluster['score_before_duplicate_adjustment'] = cluster['score']
        maximum=max(c['unique_evidence_count'] for c in clusters)
        for cluster in clusters:
            cluster['duplicate_adjusted_scale_score'] = round(100*math.log1p(cluster['unique_evidence_count'])/math.log1p(maximum),4)
            cluster['duplicate_adjusted_score'] = round((cluster['coverage_score']*config['coverage_weight']+cluster['duplicate_adjusted_scale_score']*config['scale_weight'])/(config['coverage_weight']+config['scale_weight']),4)
        clusters.sort(key=lambda c:(-c['score'],c['id']))
        for index,cluster in enumerate(clusters,1):cluster['priority']=index

    members = [rid for c in clusters for rid in c['records']]
    evaluation['value_diagnostics']=local_value.diagnostics(clusters,source_count,(config['coverage_weight'],config['scale_weight']),positives)
    tie_sizes={cid:len(group['cluster_ids']) for group in evaluation['value_diagnostics']['tie_groups'] for cid in group['cluster_ids']}
    for c in clusters:c['same_score_count']=tie_sizes.get(c['id'],1)
    evaluation['structure_valid'] = len(members) == len(set(members)) and set(members) == {r['id'] for r in positives}
    evaluation['screening_flow']=screening_flow(judgments,config['threshold'])
    exclusions = Counter(reason for j in judgments.values() for reason in j['failed_checks'])
    signature = json.dumps({'direction': batch['direction'], 'records': records}, ensure_ascii=False, sort_keys=True)
    return {'version': VERSION, 'sklearn_version': sklearn.__version__, 'seed': SEED,
            'snapshot_schema_version':2,'direction':batch['direction'],
            'direction_scope':direction_scope(batch['direction'],config),
            'runtime_versions':{'python':sys.version,'numpy':np.__version__,'sklearn':sklearn.__version__},
            'input_sha256': hashlib.sha256(signature.encode()).hexdigest(), 'config': config,
            'representation': representation, 'judgments': judgments, 'clusters': clusters,
            'embedding_metadata': embedding_metadata, 'effective_distance_threshold': cluster_threshold,
            'evaluation': evaluation, 'record_count': len(records), 'candidate_count': len(positives),
            'exclusions': dict(exclusions), 'source_count': source_count, 'duplicate_diagnostics': duplicates,
            'preprocessing_version': preprocessing.VERSION,
            'score_formula': '覆盖=100×簇内网站数/选定网站数；规模=100×log(1+簇记录数)/log(1+最大簇记录数)；近重复调整分仅作补充诊断，来源覆盖不等同独立证据；按配置权重归一化加权',
            'conclusion': f'{len(records)}条记录经规则筛选保留{len(positives)}条候选，形成{len(clusters)}个主题。'
                          '可查看主题、来源证据和价值排序，并继续整理立项策划。',
            'rules': {'patterns': PATTERNS, 'functions': FUNCTION_TERMS, 'industries': INDUSTRY_TERMS,
                      'topic_scenarios':SCENARIO_TERMS,'topic_scene_min_support':'strict_majority',
                      'office_scope': OFFICE, 'ai_need_max_character_distance': 600}}
