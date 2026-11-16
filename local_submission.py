"""Validate consistency of the four result tables from one saved analysis."""
import math
from analysis_engine import FUNCTIONS,INDUSTRIES


def check(result):
    records=result['input_records'];judgments=result['judgments'];clusters=result['clusters']
    ids=[row['id'] for row in records];id_set=set(ids);by_id={row['id']:row for row in records}
    positives={rid for rid,row in judgments.items() if row.get('opportunity')==1}
    members=[rid for cluster in clusters for rid in cluster.get('records',[])]
    def finite_number(value,low,high):
        return type(value) in (int,float) and math.isfinite(value) and low<=value<=high
    checks=[
        ('records','采集记录编号完整',len(ids)==len(id_set) and len(records)==result['record_count']),
        ('fields','来源、链接与清洗正文完整',all(all(isinstance(row.get(key),str) and row[key].strip() for key in ('id','source','url','content')) for row in records)),
        ('judgments','逐条判别覆盖全部清洗记录',set(judgments)==id_set),
        ('scores','判别标记与置信度范围有效',all(type(row.get('opportunity')) is int and row['opportunity'] in (0,1) and finite_number(row.get('confidence'),0,1) for row in judgments.values())),
        ('labels','机会记录的功能与行业符合标签体系',all(row.get('function') in FUNCTIONS and row.get('industry') in INDUSTRIES if row.get('opportunity')==1 else not row.get('function') and not row.get('industry') for row in judgments.values())),
        ('members','主题成员与机会记录一一对应',len(members)==len(set(members)) and set(members)==positives and all(cluster.get('records') for cluster in clusters)),
        ('themes','主题编号、名称、分类及数量完整',len({c.get('id') for c in clusters})==len(clusters) and all(c.get('id') and isinstance(c.get('name'),str) and c['name'].strip() and c.get('function') in FUNCTIONS and c.get('industry') in INDUSTRIES and c.get('count')==len(c.get('records',[])) for c in clusters)),
        ('sources','主题来源覆盖与原记录一致',all(set(c.get('sources',[]))=={by_id[rid]['source'] for rid in c.get('records',[]) if rid in by_id} for c in clusters)),
        ('ranking','价值分与优先级有效',all(finite_number(c.get('score'),0,100) and c.get('priority')==index for index,c in enumerate(clusters,1)) and all(a['score']>=b['score'] for a,b in zip(clusters,clusters[1:]))),
    ]
    items=[{'key':key,'label':label,'passed':bool(passed)} for key,label,passed in checks]
    return {'passed':all(row['passed'] for row in items),'checks':items,
            'rows':{'result1.csv':len(records),'result2.csv':len(judgments),'result3.csv':len(clusters),'result4.csv':len(clusters)},
            'empty_opportunities':not positives,'scope':'文件字段、编号关联、标签、数值与排序核对'}
