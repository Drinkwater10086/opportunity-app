"""Explicit, reproducible download of model data only; no remote Python code.

Run manually before choosing E5. The web analysis route never downloads files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import requests

MODEL_ID = 'intfloat/multilingual-e5-small'
REVISION = '614241f622f53c4eeff9890bdc4f31cfecc418b3'
FILES = ('onnx/config.json','onnx/tokenizer.json','onnx/model_qint8_avx512_vnni.onnx')


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def setup(directory,proxy=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    session=requests.Session()
    if proxy:session.proxies.update({'https':proxy,'http':proxy})
    # No implicit Hugging Face login/token lookup.
    response=session.get(f'https://huggingface.co/api/models/{MODEL_ID}/revision/{REVISION}',params={'blobs':'true'},timeout=30)
    response.raise_for_status();info=response.json()
    if info['sha']!=REVISION:raise ValueError('模型版本不匹配')
    siblings={s['rfilename']:s for s in info['siblings']}
    hashes={}
    for name in FILES:
        expected=siblings[name].get('lfs',{}).get('sha256')
        target=directory/Path(name).name
        if target.exists() and expected and digest(target)==expected:
            print(f'{target.name}: verified existing file',flush=True)
        else:
            temporary=target.with_suffix(target.suffix+'.part')
            size=0
            with session.get(f'https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{name}',stream=True,timeout=(15,60)) as download:
                download.raise_for_status()
                with temporary.open('wb') as output:
                    for block in download.iter_content(1024*1024):
                        size+=len(block)
                        if size>200_000_000:raise ValueError('文件超过200MB保护限制')
                        output.write(block)
            actual=digest(temporary)
            if expected and actual!=expected:raise ValueError('模型文件校验失败，未安装')
            temporary.replace(target)
            print(f'{target.name}: {size} bytes downloaded and checked',flush=True)
        hashes[target.name]=digest(target)
    manifest={'model_id':MODEL_ID,'revision':REVISION,'license':'MIT',
              'source':f'https://huggingface.co/{MODEL_ID}/tree/{REVISION}',
              'files':hashes,'file_names':list(hashes),'format':'ONNX qint8; tokenizer JSON',
              'note':'模型仅作本地文本特征提取；下载不包含用户采集文本或API密钥'}
    (directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',default=str(Path(__file__).resolve().parent/'models/e5-small'))
    parser.add_argument('--proxy',default=None)
    args=parser.parse_args()
    setup(args.directory,args.proxy)
