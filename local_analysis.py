"""Offline, versioned research baseline. No network/model-provider calls.

Rules are engineering hypotheses, not ground truth or calibrated probabilities.
LSA is corpus-local latent semantics, not a pretrained multilingual encoder.
"""
import hashlib
import json
import re
import math
import local_preprocessing as preprocessing
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

VERSION = 'local-rules-lsa-v2-context'
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
OFFICE = '会议,邮件,审批,合同,办公,销售,人事,财务,meeting,email,approval,contract,office,knowledge base,sales,crm,human resources,invoice,payroll'
PATTERNS = {
    'need': r'有没有|求推荐|求助|需要|希望|耗时|费时|手动|无法|困难|痛点|重复录入|效率低|\b(?:needs?|needed|looking for|struggl\w*|manual(?:ly)?|time.consuming|cannot|can.t|unable|problem|feature request|how (?:can|do|to))\b',
    'ai': r'人工智能|大模型|语言模型|机器学习|语音识别|图像识别|\b(?:AI|LLMs?|GPT\w*|machine learning|Whisper|OCR|RAG|neural|language model)\b',
    'feasible': r'模型|识别|检索|转写|分类|预测|抽取|\b(?:API|model|OCR|Whisper|retrieval|transcri\w*|classif\w*|extract\w*|predict\w*)\b',
    'context': r'用户|员工|客户|团队|会议|文档|邮件|合同|报表|流程|患者|学生|教师|\b(?:users?|employees?|customers?|teams?|meetings?|documents?|emails?|contracts?|reports?|workflow|patients?|students?|teachers?|invoices?)\b',
    'exclude': r'购买链接|限时优惠|纯教程|入门教程|\b(?:sponsored|buy now|limited.time offer|affiliate link|step.by.step tutorial|beginner.s guide)\b',
    'negated_ai': r'不(?:需要|使用|用)\s*(?:AI|人工智能|大模型)|\b(?:without|no need for|do not (?:use|need)|don.t (?:use|need))\s+(?:an?\s+)?(?:AI|LLM|GPT|machine learning)\b',
}


def terms(text):
    return [s.strip() for s in re.split(r'[,，;；\n]', text) if s.strip()]


def contains(text, term):
    # ASCII word boundaries prevent AI matching "email" or RAG matching "storage".
    pattern = r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])' if term.isascii() else re.escape(term)
    return re.search(pattern, text, re.I) is not None


def evidence(text, pattern):
    match = re.search(pattern, text, re.I)
    if not match:
        return None
    start, end = max(0, match.start()-80), min(len(text), match.end()+120)
    return {'start': start, 'end': end, 'text': text[start:end],
            'match_start': match.start(), 'match_end': match.end(), 'match': match.group()}


def nearby_evidence(text):
    """Inspect all matches, including late passages in long documents."""
    needs = list(re.finditer(PATTERNS['need'], text, re.I))
    ai_matches = list(re.finditer(PATTERNS['ai'], text, re.I))
    j = 0
    for need in needs:
        while j < len(ai_matches) and ai_matches[j].start() < need.start()-600:
            j += 1
        if j < len(ai_matches) and abs(ai_matches[j].start()-need.start()) <= 600:
            spans = []
            for match in (need, ai_matches[j]):
                start, end = max(0, match.start()-80), min(len(text), match.end()+120)
                spans.append({'start':start,'end':end,'text':text[start:end],
                              'match_start':match.start(),'match_end':match.end(),'match':match.group()})
            return spans
    return None


def label(text, dictionary, default):
    scores = {name: sum(contains(text, t) for t in terms(words)) for name, words in dictionary.items()}
    best = max(scores, key=scores.get)
    return (best if scores[best] else default), scores


def judge_window(record, direction, config):
    text = record['content']
    hits = {key: evidence(text, pattern) for key, pattern in PATTERNS.items()}
    paired = nearby_evidence(text)
    if paired:
        hits['need'], hits['ai'] = paired
    scope = terms(config.get('direction_terms', '')) or terms(direction)
    if '办公' in direction or 'office' in direction.lower():
        scope += terms(OFFICE)
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
    weights = {'quality': .05, 'relevant': .15, 'real_need': .25, 'context': .15,
               'ai_core': .20, 'feasible': .15, 'classified': .05}
    score = round(sum(weights[k] for k, passed in checks.items() if passed), 4)
    excluded = bool(hits['exclude']) or supporting_only
    opportunity = int(all(checks.values()) and not excluded and score >= config['threshold'])
    failures = [key for key, passed in checks.items() if not passed] + (['exclude'] if hits['exclude'] else []) + (['technical_context_only'] if supporting_only else [])
    def quote(key):
        return hits[key]['text'] if hits[key] else ''
    return {**checks, 'opportunity': opportunity, 'excluded': excluded, 'confidence': score,
            'score_kind': '规则完整性分数，非校准概率；全部硬条件通过才保留',
            'function': function if opportunity else '', 'industry': industry if opportunity else '',
            'label_scores': {'function': function_scores, 'industry': industry_scores},
            'scope_terms': scope_hits, 'evidence_spans': hits, 'failed_checks': failures,
            'reason': '规则条件全部满足，仍需验证语义正确性' if opportunity else '规则未通过：'+', '.join(failures),
            'pain': quote('need'), 'target_user': quote('context'), 'evidence': quote('need'),
            'need_evidence': quote('need'), 'user_evidence': quote('context'),
            'ai_evidence': quote('ai'), 'feasibility_evidence': quote('feasible'),
            'need_kind': 'explicit_request' if hits['need'] else 'none',
            'relevant_evidence': scope_hits}


def judge(record, direction, config):
    original = record['content']
    structured = preprocessing.structure(original)
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
        candidates.append((result['opportunity'], result['confidence'], -start, start, end, result))
        # All retained scores are 1 under current hard gates; the earliest full match wins.
        if result['opportunity']:
            break
    if not candidates and fallback:
        _, start, end, window = fallback
        result = judge_window({**record, 'content': window}, direction, config)
        candidates.append((result['opportunity'], result['confidence'], -start, start, end, result))
    if candidates:
        _, _, _, start, end, result = max(candidates, key=lambda x:x[:3])
    else:
        start, end = 0, len(original)
        result = judge_window({**record, 'content': structured['text']}, direction, config)
    for span in result['evidence_spans'].values():
        if span:
            for field in ('start','end','match_start','match_end'): span[field] += start
            span['text'] = original[span['start']:span['end']]
            span['match'] = original[span['match_start']:span['match_end']]
    for target, source in [('evidence','need'),('need_evidence','need'),('pain','need'),
                           ('user_evidence','context'),('target_user','context'),
                           ('ai_evidence','ai'),('feasibility_evidence','feasible')]:
        span=result['evidence_spans'][source]
        result[target]=span['text'] if span else ''
    result['selected_context']={'start':start,'end':end,'text':original[start:end],
                                'method':'同段最多3个相邻句；上下文最长1200字符，超长单句完整保留'}
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
    return {'sample_count': n, 'cluster_count': len(counts), 'silhouette': score, 'reason': reason,
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
                      not j['failed_checks'] and j['confidence'] >= t for j in judgments.values())}
                      for t in sorted({.5, .7, .9, config['threshold']})],
                  'ablation': {key: sum(not j['excluded'] and all(j[k] for k in
                      ('quality','relevant','real_need','context','ai_core','feasible','classified') if k != key)
                      and j['confidence'] >= config['threshold'] for j in judgments.values())
                      for key in ('relevant', 'real_need', 'ai_core', 'feasible')},
                  'note': '没有人工真值，不报告准确率或F1。ARI比较距离阈值扰动下的分组，不是独立重复运行或正确性。规则分数为条件加权，硬门槛可能使阈值变化不改变候选数。'}
    clusters, representation = [], '无候选，不构建向量'
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
        representation = 'TF-IDF（候选少于8条，未执行LSA以避免极低维度过度合并）'
        if len(positives) >= 8 and dimensions >= 2:
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
        labels = partition(distances, config['distance_threshold'])
        base_labels = partition(baseline_distances, config['distance_threshold'])
        evaluation['primary'] = diagnostic(distances, labels)
        evaluation['baseline'] = diagnostic(baseline_distances, base_labels)
        evaluation['primary_in_lexical_space'] = diagnostic(original_distances, labels)
        evaluation['baseline_labels'] = dict(zip([r['id'] for r in positives], map(int, base_labels)))
        for threshold in sorted({max(.05, config['distance_threshold']-.1), min(1.5, config['distance_threshold']+.1)}):
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
            title = '、'.join(k['term'] for k in keywords)
            clusters.append({'name': f'围绕{title[:60]}的{function}需求' if title else representative['title'][:90] or representative['content'][:90],
                             'name_method': '原文关键词按记录覆盖与标题命中提取，使用固定句式概括；须核对代表记录',
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
    evaluation['structure_valid'] = len(members) == len(set(members)) and set(members) == {r['id'] for r in positives}
    exclusions = Counter(reason for j in judgments.values() for reason in j['failed_checks'])
    signature = json.dumps({'direction': batch['direction'], 'records': records}, ensure_ascii=False, sort_keys=True)
    return {'version': VERSION, 'sklearn_version': sklearn.__version__, 'seed': SEED,
            'input_sha256': hashlib.sha256(signature.encode()).hexdigest(), 'config': config,
            'representation': representation, 'judgments': judgments, 'clusters': clusters,
            'evaluation': evaluation, 'record_count': len(records), 'candidate_count': len(positives),
            'exclusions': dict(exclusions), 'source_count': source_count, 'duplicate_diagnostics': duplicates,
            'preprocessing_version': preprocessing.VERSION,
            'score_formula': '覆盖=100×簇内网站数/选定网站数；规模=100×log(1+簇记录数)/log(1+最大簇记录数)；近重复调整分仅作补充诊断，来源覆盖不等同独立证据；按配置权重归一化加权',
            'conclusion': f'{len(records)}条记录经规则筛选保留{len(positives)}条候选，形成{len(clusters)}个主题。'
                          '候选及排序仅为样本内研究线索，未验证市场需求或分类准确率。',
            'rules': {'patterns': PATTERNS, 'functions': FUNCTION_TERMS, 'industries': INDUSTRY_TERMS,
                      'office_scope': OFFICE, 'ai_need_max_character_distance': 600}}
