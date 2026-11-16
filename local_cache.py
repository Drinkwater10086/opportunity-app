"""Bounded process-memory cache. No persistent text or shared mutable results."""
import hashlib
import json
import threading
from collections import OrderedDict

MAX_BYTES=32*1024*1024
MAX_ENTRIES=5000
_LOCK=threading.Lock()
_ITEMS=OrderedDict()
_BYTES=0
_HITS=0
_MISSES=0


def cached(namespace,payload,compute):
    global _BYTES,_HITS,_MISSES
    signature=json.dumps(payload,ensure_ascii=False,sort_keys=True,allow_nan=False)
    key=(namespace,hashlib.sha256(signature.encode('utf8')).hexdigest())
    with _LOCK:
        if key in _ITEMS:
            _HITS+=1
            value,size=_ITEMS[key];_ITEMS.move_to_end(key)
            return json.loads(value)
        _MISSES+=1
    result=compute()
    value=json.dumps(result,ensure_ascii=False,allow_nan=False)
    size=len(value.encode('utf8'))+len(namespace.encode('utf8'))+64
    if size<=MAX_BYTES:
        with _LOCK:
            if key in _ITEMS:_BYTES-=_ITEMS.pop(key)[1]
            while _ITEMS and (_BYTES+size>MAX_BYTES or len(_ITEMS)>=MAX_ENTRIES):
                _,(_,evicted)=_ITEMS.popitem(last=False);_BYTES-=evicted
            _ITEMS[key]=(value,size);_BYTES+=size
    return json.loads(value)


def stats():
    with _LOCK:return {'hits':_HITS,'misses':_MISSES,'entries':len(_ITEMS),'bytes':_BYTES,'max_bytes':MAX_BYTES}


def clear():
    global _BYTES,_HITS,_MISSES
    with _LOCK:
        _ITEMS.clear();_BYTES=0;_HITS=0;_MISSES=0
