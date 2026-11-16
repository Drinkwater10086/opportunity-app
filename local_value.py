"""Diagnostics for mandatory source coverage / record scale scores only."""
import math
from collections import Counter, defaultdict

VERSION='value-weights-and-source-removal-v2'


def source_removal(clusters,records,source_count,weights):
    """Delete one candidate platform at a time; keep the original themes fixed."""
    note=('固定本次候选与主题成员，逐次删除一个实际提供候选的平台，不重新判别或聚类；'
          '覆盖分分母同时从选定平台数减1，规模分按剩余最大簇重新归一化。'
          '排名按严格高分主题数+1计算，同分同名次；不改变正式评分或排名。'
          '这是样本来源依赖诊断，不证明来源独立、语义正确或市场价值；不同删源情景的归一化分数不能直接作绝对价值比较。')
    result={'note':note,'status':'no_candidates','scenarios':[],'themes':[],
            'baseline_top_ids':[],'candidate_sources':[],'ranking_change_scenario_count':None,
            'comparable_scenario_count':0}
    if not clusters:return result
    if records is None:
        return {**result,'status':'unavailable','reason':'未提供该次候选输入，不补算或伪造来源诊断'}
    by_id={r['id']:r for r in records}
    members=[rid for c in clusters for rid in c['records']]
    if (len(by_id)!=len(records) or len(members)!=len(set(members)) or set(members)!=set(by_id)
        or any(not c['records'] for c in clusters)
        or len({c['id'] for c in clusters})!=len(clusters)):
        return {**result,'status':'invalid_partition','reason':'主题成员重复、遗漏或与候选输入不一致，未计算'}
    counts={c['id']:Counter(by_id[rid]['source'] for rid in c['records']) for c in clusters}
    platforms=sorted({r['source'] for r in records})
    if source_count<len(platforms) or not platforms:
        return {**result,'status':'invalid_sources','reason':'选定平台数量少于候选实际平台数，未计算'}
    def ranks(scores):
        # Ties must not gain an invented preference from cluster IDs.
        higher=0;positions={}
        for score,n in sorted(Counter(scores.values()).items(),reverse=True):
            positions[score]=higher+1;higher+=n
        return {cid:positions[score] for cid,score in scores.items()}
    baseline_scores={c['id']:c['score'] for c in clusters}
    baseline_ranks=ranks(baseline_scores)
    result.update(status='ok' if len(platforms)>1 else 'single_source',candidate_sources=platforms,
                  baseline_top_ids=sorted(cid for cid,rank in baseline_ranks.items() if rank==1))
    for platform in platforms:
        remaining={cid:{source:n for source,n in count.items() if source!=platform} for cid,count in counts.items()}
        sizes={cid:sum(count.values()) for cid,count in remaining.items()}
        maximum=max(sizes.values())
        scores={cid:round((100*len(remaining[cid])/(source_count-1)*weights[0]
                         +100*math.log1p(n)/math.log1p(maximum)*weights[1])/sum(weights),4)
                for cid,n in sizes.items() if n}
        positions=ranks(scores)
        rows=[{'id':cid,'remaining_count':sizes[cid],'sources':sorted(remaining[cid]),
               'score':scores.get(cid),'rank':positions.get(cid),'baseline_rank':baseline_ranks[cid],
               'rank_change':positions[cid]-baseline_ranks[cid] if cid in positions else None}
              for cid in sorted(sizes)]
        result['scenarios'].append({'removed_source':platform,
            'removed_record_ids':sorted(rid for rid,r in by_id.items() if r['source']==platform),
            'remaining_record_count':sum(sizes.values()),'remaining_source_denominator':source_count-1,
            'empty_theme_ids':sorted(cid for cid,n in sizes.items() if not n),
            'top_ids':sorted(cid for cid,rank in positions.items() if rank==1),
            'ranking_available':bool(scores),'themes':rows})
    rows_by_theme={c['id']:[] for c in clusters}
    for case in result['scenarios']:
        for row in case['themes']:rows_by_theme[row['id']].append(row)
    for c in clusters:
        cid=c['id'];rows=rows_by_theme[cid]
        disappeared=[case['removed_source'] for case,row in zip(result['scenarios'],rows) if not row['remaining_count']]
        drops=[row['rank_change'] for row in rows if row['rank_change'] is not None]
        result['themes'].append({'id':cid,'baseline_rank':baseline_ranks[cid],
            'source_counts':dict(sorted(counts[cid].items())),
            'dominant_source_share':max(counts[cid].values())/len(c['records']),
            'single_platform':len(counts[cid])==1,'disappears_when_removing':disappeared,
            'surviving_scenarios':len(rows)-len(disappeared),'scenario_count':len(rows),
            'maximum_rank_drop':max(0,max(drops)) if drops else None})
    # Compare only pairs still present; disappearance is reported separately.
    changed=comparable=0
    for case in result['scenarios']:
        scores={row['id']:row['score'] for row in case['themes'] if row['score'] is not None}
        ids=sorted(scores)
        if len(ids)<2:continue
        comparable+=1
        def ordering(values):
            groups=defaultdict(list)
            for cid,score in values.items():groups[score].append(cid)
            return [sorted(groups[score]) for score in sorted(groups,reverse=True)]
        if ordering(scores)!=ordering({cid:baseline_scores[cid] for cid in ids}):changed+=1
    result['comparable_scenario_count']=comparable
    result['ranking_change_scenario_count']=changed if comparable else None
    return result


def diagnostics(clusters,source_count,weights,records=None):
    removal=source_removal(clusters,records,source_count,weights)
    if not clusters:
        return {'version':VERSION,'tie_groups':[],'all_scores_equal':False,'weight_grid':[],'source_removal':removal,
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
    return {'version':VERSION,'source_removal':removal,'tie_groups':[{'score':score,'cluster_ids':sorted(ids)}
                for score,ids in sorted(ties.items(),reverse=True) if len(ids)>1],
            'all_scores_equal':len(clusters)>1 and len(ties)==1,'weight_grid':grid,
            'note':'固定网格只改变来源覆盖/记录规模权重，不重跑筛选或聚类、不自动择优；正式分保持原配置。'
                   '同分按簇编号固定展示，编号不是价值高低。权重稳定也不证明市场价值。'}
