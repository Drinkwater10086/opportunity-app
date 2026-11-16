"""Local-only multilingual E5 ONNX features, bounded without silent truncation."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
from functools import lru_cache
import threading

import numpy as np
import local_cache

MODEL_ID='intfloat/multilingual-e5-small'
REVISION='614241f622f53c4eeff9890bdc4f31cfecc418b3'
MODEL_FILE='model_qint8_avx512_vnni.onnx'
FILES=('config.json','tokenizer.json',MODEL_FILE)
LOCK=threading.Lock()
MAX_CHUNKS=20000


def model_directory():
    return Path(os.environ.get('OPPORTUNITY_E5_DIR',str(Path(__file__).resolve().parent/'models/e5-small')))


def available():
    directory=model_directory()
    return all((directory/f).is_file() for f in (*FILES,'manifest.json'))


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


@lru_cache(maxsize=2)
def load(directory,signature):
    try:
        import onnxruntime as ort
        from tokenizers import Tokenizer
    except ImportError:
        raise ValueError('句向量依赖未安装，请按requirements-semantic.txt安装本地依赖') from None
    directory=Path(directory)
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('model_id')!=MODEL_ID or manifest.get('revision')!=REVISION:
        raise ValueError('模型清单版本不受支持')
    for name in FILES:
        if digest(directory/name)!=manifest['files'].get(name):raise ValueError('本地模型哈希校验失败：'+name)
    tokenizer=Tokenizer.from_file(str(directory/'tokenizer.json'))
    tokenizer.no_truncation();tokenizer.no_padding()
    config=json.loads((directory/'config.json').read_text(encoding='utf-8'))
    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    session=ort.InferenceSession(str(directory/MODEL_FILE),sess_options=options,providers=['CPUExecutionProvider'])
    names={v.name for v in session.get_inputs()}
    if not names<= {'input_ids','attention_mask','token_type_ids'}:
        raise ValueError('ONNX输入接口不匹配，未猜测参数')
    return tokenizer,session,config,manifest


def token_chunks(text,tokenizer):
    encoded=tokenizer.encode(text,add_special_tokens=False)
    offsets=encoded.offsets
    if not offsets:raise ValueError('句向量输入没有有效token')
    # Reserve space for query prefix and special tokens. All source tokens are covered.
    start=0
    while start<len(offsets):
        stop=min(start+480,len(offsets))
        lo,hi=offsets[start][0],offsets[stop-1][1]
        # Include whitespace between chunks via overlap; metadata defines actual token coverage.
        yield {'token_start':start,'token_end':stop,'start':lo,'end':hi,'text':text[lo:hi]}
        if stop==len(offsets):break
        start=stop-32


def _embed(texts):
    directory=model_directory()
    if not available():raise ValueError('本地E5模型尚未准备，请运行setup_semantic_model.py；未自动下载或退回词面算法')
    signature=tuple((directory/f).stat().st_mtime_ns for f in (*FILES,'manifest.json'))
    with LOCK:
        tokenizer,session,config,manifest=load(str(directory.resolve()),signature)
        chunks=[];owners=[];coverage=[[] for _ in texts]
        for i,text in enumerate(texts):
            for chunk in token_chunks(text,tokenizer):
                ids=tokenizer.encode('query: '+chunk['text']).ids
                if len(ids)>512:raise ValueError('分片超过512token，未截断输入')
                chunks.append(ids);owners.append(i)
                coverage[i].append({k:v for k,v in chunk.items() if k!='text'})
                if len(chunks)>MAX_CHUNKS:raise ValueError('超过20000个语义分片保护限制，未截断')
        sums=np.zeros((len(texts),384),dtype=np.float64);weights=np.zeros(len(texts))
        for at in range(0,len(chunks),8):
            batch=chunks[at:at+8];width=max(map(len,batch));pad=int(config.get('pad_token_id',1))
            ids=np.full((len(batch),width),pad,dtype=np.int64);mask=np.zeros_like(ids)
            for i,row in enumerate(batch):ids[i,:len(row)]=row;mask[i,:len(row)]=1
            feed={'input_ids':ids,'attention_mask':mask}
            names={x.name for x in session.get_inputs()}
            if 'token_type_ids' in names:feed['token_type_ids']=np.zeros_like(ids)
            outputs=session.run(None,{key:val for key,val in feed.items() if key in names})
            tokens=outputs[0]
            if tokens.shape!=(len(batch),width,384):raise ValueError('ONNX输出不是预期的token特征')
            vectors=(tokens*mask[:,:,None]).sum(axis=1)/mask.sum(axis=1)[:,None]
            vectors/=np.maximum(np.linalg.norm(vectors,axis=1,keepdims=True),1e-12)
            for i,vector in enumerate(vectors):
                owner=owners[at+i];weight=len(batch[i])-2
                sums[owner]+=vector*weight;weights[owner]+=weight
        norms=np.linalg.norm(sums,axis=1,keepdims=True)
        if np.any(norms<1e-12) or not np.all(np.isfinite(sums)):raise ValueError('语义向量为空或含无效值')
        vectors=sums/norms
    return vectors, {'model_id':MODEL_ID,'revision':REVISION,'model_sha256':manifest['files'][MODEL_FILE],
                     'tokenizer_sha256':manifest['files']['tokenizer.json'],'license':'MIT',
                     'runtime':importlib.metadata.version('onnxruntime'),'tokenizers':importlib.metadata.version('tokenizers'),
                     'providers':['CPUExecutionProvider'],'prefix':'query: ', 'pooling':'attention-mask mean; L2 normalization; token-weighted chunk mean then L2',
                     'max_tokens':512,'chunk_tokens':480,'overlap_tokens':32,'truncated':False,
                     'coverage':coverage,'note':'预训练模型仅作本地语义特征提取，存在量化误差；多分片均值可能稀释局部需求，不保证业务正确性。'}


_EMBED_CODE=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def embed(texts):
    directory=model_directory()
    if not available():raise ValueError('本地E5模型尚未准备，请运行setup_semantic_model.py；未自动下载或退回词面算法')
    signature=[(name,(directory/name).stat().st_mtime_ns,(directory/name).stat().st_size) for name in (*FILES,'manifest.json')]
    def compute():
        vectors,metadata=_embed(texts)
        return {'vectors':vectors.tolist(),'metadata':metadata}
    result=local_cache.cached('embedding',{'code':_EMBED_CODE,'directory':str(directory.resolve()),
        'signature':signature,'texts':texts},compute)
    return np.asarray(result['vectors'],dtype=np.float64),result['metadata']
