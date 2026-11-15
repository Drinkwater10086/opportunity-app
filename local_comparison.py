"""Compare stored runs without additional collection or model calls."""
from sklearn.metrics import adjusted_rand_score


def compare(left, right):
    same_input = left['input_sha256'] == right['input_sha256']
    left_ids = {rid for rid,j in left['judgments'].items() if j['opportunity']}
    right_ids = {rid for rid,j in right['judgments'].items() if j['opportunity']}
    common = sorted(left_ids & right_ids)
    a = {rid:i for i,c in enumerate(left['clusters']) for rid in c['records']}
    b = {rid:i for i,c in enumerate(right['clusters']) for rid in c['records']}
    valid = all(rid in a and rid in b for rid in common)
    score = float(adjusted_rand_score([a[r] for r in common],[b[r] for r in common])) if same_input and valid and len(common)>=2 else None
    return {'same_input':same_input,'left_version':left['version'],'right_version':right['version'],
            'left_candidates':len(left_ids),'right_candidates':len(right_ids),'common_candidates':len(common),
            'added_ids':sorted(right_ids-left_ids),'removed_ids':sorted(left_ids-right_ids),
            'ari_on_common_candidates':score,
            'note':'ARI仅比较共同候选上的分组，不覆盖新增/移除记录，不表示准确率。相同确定性配置重复运行不能证明质量。不同输入不计算ARI。'}
