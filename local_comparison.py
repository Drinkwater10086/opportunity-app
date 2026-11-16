"""Compare stored runs without additional collection or model calls."""
from sklearn.metrics import adjusted_rand_score

VERSION='local-comparison-v2-candidate-coverage'


def partition_info(result,candidate_ids):
    members=[rid for cluster in result['clusters'] for rid in cluster['records']]
    valid=(len(members)==len(set(members)) and set(members)==candidate_ids
           and all(cluster['records'] for cluster in result['clusters']))
    labels={rid:i for i,cluster in enumerate(result['clusters']) for rid in cluster['records']}
    return labels,valid


def compare(left, right):
    same_input = left['input_sha256'] == right['input_sha256']
    left_ids = {rid for rid,j in left['judgments'].items() if j['opportunity']}
    right_ids = {rid for rid,j in right['judgments'].items() if j['opportunity']}
    common = sorted(left_ids & right_ids)
    union=left_ids|right_ids
    a,left_valid=partition_info(left,left_ids)
    b,right_valid=partition_info(right,right_ids)
    valid=left_valid and right_valid
    reason=('输入快照不同，不计算ARI' if not same_input else
            '成员编号存在遗漏、重复、非候选或空簇，不计算ARI' if not valid else
            '共同候选少于2条，不计算ARI' if len(common)<2 else '在相同输入的共同候选上计算，不覆盖候选集合变化')
    score = float(adjusted_rand_score([a[r] for r in common],[b[r] for r in common])) if same_input and valid and len(common)>=2 else None
    overlap=len(common)/len(union) if same_input and union else None
    warnings=[]
    if overlap is not None and overlap<1:warnings.append('候选集合已变化，ARI只覆盖两侧交集，不能代表全部筛选结果一致')
    if score is not None:
        for label,labels in [('当前实验',a),('所选实验',b)]:
            count=len({labels[rid] for rid in common})
            if count==1 or count==len(common):warnings.append(label+'在共同候选上全合一簇或全为单例，ARI高值不能证明有效区分主题')
    same_config=left['config']==right['config'] if 'config' in left and 'config' in right else None
    if same_config and left['version']==right['version']:warnings.append('同版本同参数的确定性重复运行不构成独立质量验证')
    return {'comparison_version':VERSION,'same_input':same_input,'same_config':same_config,
            'left_version':left['version'],'right_version':right['version'],
            'left_candidates':len(left_ids),'right_candidates':len(right_ids),'common_candidates':len(common),
            'union_candidates':len(union),'candidate_jaccard':overlap,
            'overlap_reason':'候选交集数/并集数，非准确率' if overlap is not None else '输入不同或两侧均无候选，重合率不作有效评价',
            'left_partition_valid':left_valid,'right_partition_valid':right_valid,
            'added_ids':sorted(right_ids-left_ids),'removed_ids':sorted(left_ids-right_ids),
            'ari_on_common_candidates':score,'ari_reason':reason,'warnings':warnings,
            'note':'ARI仅比较共同候选上的分组，不覆盖新增/移除记录，不表示准确率。相同确定性配置重复运行不能证明质量。不同输入不计算ARI。'}
