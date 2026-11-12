"""Unlabelled lexical diagnostics, independent of the generating LLM."""
import hashlib
import json
from functools import lru_cache

import numpy as np
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_samples, adjusted_rand_score
from sklearn.metrics.pairwise import cosine_distances

VERSION = 'char-tfidf-cosine-v3-independent-stability'
MAX_EXACT_SILHOUETTE_SAMPLES = 2000


def screening_diagnostics(judgments, threshold):
    rejected = [j for j in judgments.values() if not j['opportunity']]
    reasons = [('候选独立复核未通过', sum(j.get('verification', {}).get('approved') is False for j in rejected)),
               ('方向不相关', sum(not j['relevant'] for j in rejected)),
               ('缺少真实需求', sum(not j['real_need'] for j in rejected)),
               ('AI不是核心', sum(not j['ai_core'] for j in rejected)),
               ('可落地条件未通过', sum(not j['feasible'] for j in rejected)),
               ('模型标记排除', sum(j['excluded'] for j in rejected)),
               ('模型自评分低于阈值', sum(j['confidence'] < threshold for j in rejected)),
               ('缺失或无效的专项证据', sum(any('缺失或不是原文' in f for f in j.get('evidence_gate_failures', [])) for j in rejected))]
    gate_only = sum(all(j[k] for k in ('relevant','real_need','ai_core','feasible'))
                    and not j['excluded'] and j['confidence'] >= threshold for j in rejected)
    return {'judged_count': len(judgments), 'rejected_count': len(rejected),
            'candidate_count': len(judgments)-len(rejected), 'evidence_only_rejected': gate_only,
            'no_signal_or_vendor_count': sum(j.get('need_kind') in ('none','vendor_claim') for j in rejected),
            'reasons': [{'reason': label, 'count': count} for label,count in reasons],
            'note': '统计来自模型判断及程序证据校验，不是人工真值。同一记录可触发多项原因，不能相加作为排除总数。'}


@lru_cache(maxsize=32)
def evaluate(snapshot):
    data = json.loads(snapshot)
    records, clusters = data['records'], data['clusters']
    members = [rid for c in clusters for rid in c['records']]
    expected = set(data['positive_ids'])
    valid = len(members) == len(set(members)) and set(members) == expected
    result = {
        'version': VERSION, 'sklearn_version': sklearn.__version__,
        'input_sha256': hashlib.sha256(snapshot.encode()).hexdigest(),
        'method': '清洗原文字符2–4元TF-IDF，L2归一化，余弦距离；不使用模型生成的主题名称或痛点作为向量输入',
        'parameters': {'analyzer': 'char', 'ngram_range': [2, 4], 'max_features': 20000,
                       'sublinear_tf': True, 'norm': 'l2', 'distance': 'cosine',
                       'max_exact_silhouette_samples': MAX_EXACT_SILHOUETTE_SAMPLES},
        'record_count': len(records), 'sample_count': len(expected), 'cluster_count': len(clusters),
        'structure_valid': valid, 'silhouette': None, 'reason': '', 'per_cluster': [],
        'singleton_count': sum(len(c['records']) == 1 for c in clusters),
        'singleton_note': '单记录簇没有组内其他样本，轮廓系数按算法约定计为0；不能单独评价其聚类质量，不代表准确率为0。总体均值仍包含这些0，未修改分数。',
        'stability': {'score': None, 'valid_runs': len(data.get('valid_runs', [])),
                      'reason': '至少需要两次相同输入上的有效、非修复聚类输出；未额外调用模型'},
        'note': '无人工真值，不提供准确率、精确率或F1。词面相似不等于语义正确；不同语言和同义改写可能得低分。结构校验只检查编号完整性。稳定不代表正确。',
    }
    if not valid:
        result['reason'] = '成员存在遗漏、重复或未知编号'
        return result
    ids = sorted(expected)
    runs = data.get('valid_runs', [])
    if len(runs) >= 2 and len(expected) >= 2:
        partitions = [{rid: i for i, c in enumerate(run) for rid in c['records']} for run in runs]
        agreements = [adjusted_rand_score([a[r] for r in ids], [b[r] for r in ids])
                      for i, a in enumerate(partitions) for b in partitions[i+1:]]
        result['stability'] = {'score': round(float(np.mean(agreements)), 6), 'valid_runs': len(runs),
                               'reason': '相同输入历次有效非修复输出的平均调整兰德指数（ARI）；稳定不代表正确；单簇或全部单例的一致可能是退化结果'}
    if not 2 <= len(clusters) <= len(expected)-1:
        result['reason'] = '轮廓系数需满足：至少2个簇，且簇数小于样本数'
        return result
    if len(expected) > MAX_EXACT_SILHOUETTE_SAMPLES:
        result['reason'] = (f'候选超过{MAX_EXACT_SILHOUETTE_SAMPLES}条，精确轮廓系数的成对距离矩阵超出本机保护范围；'
                            '未静默抽样、删除记录或伪造分数，历史一致性仍独立评价')
        return result
    by_id = {r['id']: r['content'] for r in records}
    ids = sorted(expected)
    if any(rid not in by_id or len(by_id[rid].strip()) < 2 for rid in ids):
        result['reason'] = '存在缺失或过短的原文，未删除样本或伪造分数'
        return result
    labels_by_id = {rid: i for i, c in enumerate(clusters) for rid in c['records']}
    labels = [labels_by_id[rid] for rid in ids]
    vectorizer = TfidfVectorizer(analyzer='char', ngram_range=(2, 4), max_features=20000,
                                 sublinear_tf=True, norm='l2')
    try:
        vectors = vectorizer.fit_transform([by_id[rid] for rid in ids])
    except ValueError:
        result['reason'] = '原文无法构建有效词表'
        return result
    if np.any(np.asarray(vectors.getnnz(axis=1)) == 0):
        result['reason'] = '存在零向量，无法可靠计算距离'
        return result
    distances = cosine_distances(vectors)
    np.fill_diagonal(distances, 0)
    if np.max(distances) < 1e-12:
        result['reason'] = '全部原文向量相同，无法评价分组区分度'
        return result
    scores = silhouette_samples(distances, labels, metric='precomputed')
    result['silhouette'] = round(float(np.mean(scores)), 6)
    result['reason'] = '可计算；范围-1到1，越高表示当前词面向量空间中的簇内更紧凑、簇间更分离，不是准确率'
    result['per_cluster'] = [
        {'name': c['name'], 'count': len(c['records']),
         'singleton': len(c['records']) == 1,
         'interpretation': '单记录：按约定计0，不能单独评价' if len(c['records']) == 1 else '多记录簇的平均轮廓系数',
         'silhouette': round(float(np.mean([scores[j] for j, rid in enumerate(ids) if labels_by_id[rid] == i])), 6)}
        for i, c in enumerate(clusters)]
    result['conclusion'] = (
        f"{len(expected)}条候选分成{len(clusters)}簇，其中{result['singleton_count']}个单记录簇。"
        + ('当前原文词面空间的分组分离度较弱，不能据此证明语义聚类有效。' if result['silhouette'] <= 0
           else '当前原文词面空间存在一定分离度，但不能据此证明语义判断正确。'))
    return result
