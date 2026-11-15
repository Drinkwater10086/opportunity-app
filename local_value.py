"""Diagnostics for mandatory source coverage / record scale scores only."""
import math
from collections import defaultdict

VERSION='value-ties-and-weight-grid-v1'


def diagnostics(clusters,source_count,weights):
    if not clusters:
        return {'version':VERSION,'tie_groups':[],'all_scores_equal':False,'weight_grid':[],
                'note':'无主题，不计算价值排序敏感性。'}
    ties=defaultdict(list)
    for c in clusters:ties[c['score']].append(c['id'])
    ratio=weights[0]/sum(weights)
    maximum=max(c['count'] for c in clusters)
    grid=[]
    for weight in sorted({0.,.25,.5,.6,.75,1.,ratio}):
        scores={c['id']:round((100*len(c['sources'])/max(source_count,1))*weight+
                             (100*math.log1p(c['count'])/math.log1p(maximum))*(1-weight),4)
                for c in clusters}
        # Preserve the formal result exactly at the configured weights.
        if weight==ratio:scores={c['id']:c['score'] for c in clusters}
        order=sorted(scores,key=lambda cid:(-scores[cid],cid))
        grid.append({'coverage_weight':weight,'scale_weight':1-weight,'scores':scores,
                     'ordered_ids':order,'top_ids':[cid for cid in order if scores[cid]==scores[order[0]]]})
    return {'version':VERSION,'tie_groups':[{'score':score,'cluster_ids':sorted(ids)}
                for score,ids in sorted(ties.items(),reverse=True) if len(ids)>1],
            'all_scores_equal':len(clusters)>1 and len(ties)==1,'weight_grid':grid,
            'note':'固定网格只改变来源覆盖/记录规模权重，不重跑筛选或聚类、不自动择优；正式分保持原配置。'
                   '同分按簇编号固定展示，编号不是价值高低。权重稳定也不证明市场价值。'}
