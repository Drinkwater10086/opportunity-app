"""Function/industry catalogue and deterministic opportunity ranking."""

import math

FUNCTIONS = ['图像识别','语义分析','语音处理','文本生成','对话问答','推荐系统','知识检索','数据挖掘','多模态融合','智能体编排','自动化流程','预测分析','审核审查','搜索匹配','翻译转写','视频理解']

INDUSTRIES = ['金融','教育','医疗','法律','电商','零售','房地产','制造','物流','游戏','餐饮','农业','政务','汽车','家居','交通','能源','通信','娱乐','体育','旅游','保险','建筑','环保','科研','人力资源','媒体出版','营销广告','外贸','其他']

def rank_clusters(clusters, records, source_count, weights):
    if not clusters:
        return []
    by_id = {r['id']: r for r in records}
    maximum = max(len(c['records']) for c in clusters)
    ranked = []
    for index, cluster in enumerate(clusters, 1):
        sources = sorted({by_id[r]['source'] for r in cluster['records']})
        coverage = 100 * len(sources) / max(source_count, 1)
        scale = 100 * math.log1p(len(cluster['records'])) / math.log1p(maximum)
        score = (coverage * weights[0] + scale * weights[1]) / sum(weights)
        ranked.append({**cluster, 'id': f'C{index}', 'sources': sources,
                       'count': len(cluster['records']), 'coverage_score': round(coverage, 4),
                       'scale_score': round(scale, 4), 'score': round(score, 4)})
    ranked.sort(key=lambda c: (-c['score'], c['id']))
    for i, c in enumerate(ranked, 1):
        c['priority'] = i
    return ranked
