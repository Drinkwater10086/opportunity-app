"""Replay an exported local experiment. No collection or provider API calls."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import sklearn
import numpy as np
import local_analysis
import local_preprocessing
import local_embeddings
import evidence_scoring
import context_rules
import local_value
import analysis_engine
from local_routes import LocalConfig

MODULES=(local_analysis,local_preprocessing,local_embeddings,evidence_scoring,context_rules,local_value,analysis_engine)
OUTPUT_KEYS=('judgments','clusters','evaluation','representation','input_sha256',
             'candidate_count','record_count','duplicate_diagnostics')


def code_hashes():
    return {m.__name__:hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest() for m in MODULES}


def replay(document,direction=None,allow_code_change=False):
    saved=document.get('result',document)
    if not isinstance(saved,dict):raise ValueError('实验结果必须是JSON对象')
    scope=saved.get('direction')
    if scope is None:scope=direction
    elif direction is not None and scope!=direction:raise ValueError('指定方向与保存方向不一致')
    if not isinstance(scope,str) or not scope.strip():
        raise ValueError('旧实验缺少研究方向；请通过--direction提供原方向，程序将核对输入哈希')
    records=saved.get('input_records')
    if not isinstance(records,list) or not records or not all(isinstance(r,dict) and isinstance(r.get('id'),str) and isinstance(r.get('content'),str) for r in records):
        raise ValueError('缺少完整输入记录')
    if len(records)>local_analysis.MAX_RECORDS or sum(len(r['content']) for r in records)>local_analysis.MAX_CHARACTERS:
        raise ValueError('输入超出本地分析保护范围，不截断重放')
    ids=[r['id'] for r in records]
    if len(set(ids))!=len(ids):raise ValueError('记录编号重复')
    records=sorted(records,key=lambda r:r['id'])
    signature=json.dumps({'direction':scope,'records':records},ensure_ascii=False,sort_keys=True)
    input_hash=hashlib.sha256(signature.encode()).hexdigest()
    if input_hash!=saved.get('input_sha256'):raise ValueError('输入哈希不匹配，原文、元数据或方向已变化')
    config=LocalConfig.model_validate(saved['config']).model_dump()
    count=saved.get('source_count')
    if type(count) is not int or count<1:raise ValueError('缺少有效来源平台总数，不能重建覆盖分')
    if any(key not in saved for key in OUTPUT_KEYS):raise ValueError('缺少待比较的完整实验输出')
    hashes=code_hashes();stored=saved.get('source_hashes',{})
    changes=[key for key,value in hashes.items() if stored.get(key)!=value]
    versions=[]
    if saved.get('version')!=local_analysis.VERSION:versions.append('analysis_version')
    if saved.get('sklearn_version')!=sklearn.__version__:versions.append('sklearn_version')
    runtime={'python':sys.version,'numpy':np.__version__,'sklearn':sklearn.__version__}
    if saved.get('runtime_versions')!=runtime:versions.append('runtime_versions')
    if (changes or versions) and not allow_code_change:
        raise ValueError('代码或运行库与原实验不一致；使用原版本，或显式--allow-code-change进行新旧对照')
    current=local_analysis.analyze({'direction':scope},records,config,count)
    def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False)
    differences=[key for key in OUTPUT_KEYS if canonical(saved[key])!=canonical(current[key])]
    before={k for k,v in saved['judgments'].items() if v['opportunity']}
    after={k for k,v in current['judgments'].items() if v['opportunity']}
    return {'input_verified':True,'input_sha256':input_hash,'same_outputs':not differences,
            'different_fields':differences,'changed_code_modules':changes,'changed_versions':versions,
            'saved_version':saved['version'],'current_version':current['version'],
            'records':len(records),'before_candidates':len(before),'after_candidates':len(after),
            'added_ids':sorted(after-before),'removed_ids':sorted(before-after),
            'note':'仅比较指定输入的程序输出；一致不证明需求判断正确或实验具有独立原创性。未重新采集或调用生成式模型。'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence',type=Path,help='网页导出的证据与实验参数JSON')
    parser.add_argument('--direction',help='仅用于补充旧版本缺失的原研究方向')
    parser.add_argument('--allow-code-change',action='store_true',help='显式允许用当前代码对照旧输出，不表示复现旧版本')
    parser.add_argument('--output',type=Path,help='仅保存不含原文的对照摘要；默认打印')
    args=parser.parse_args(argv)
    try:
        if args.evidence.stat().st_size>256*1024*1024:raise ValueError('快照超过256MB保护上限')
        document=json.loads(args.evidence.read_text(encoding='utf-8-sig'))
        if not isinstance(document,dict):raise ValueError('文件顶层必须是JSON对象')
        result=replay(document,args.direction,args.allow_code_change)
        text=json.dumps(result,ensure_ascii=False,indent=2)
        if args.output:
            if args.output.resolve()==args.evidence.resolve():raise ValueError('摘要输出不能覆盖输入证据')
            args.output.write_text(text+'\n',encoding='utf8')
        else:print(text)
        return 0 if result['same_outputs'] else 1
    except (ValueError,KeyError,TypeError,OSError) as error:
        parser.exit(2,str(error)+'\n')


if __name__=='__main__':raise SystemExit(main())
