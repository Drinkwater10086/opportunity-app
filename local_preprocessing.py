"""Conservative, offset-preserving analysis views. Original records are immutable."""
import re

VERSION = 'structure-and-duplicate-v2'
EXCLUDED = re.compile(r'```[\s\S]*?(?:```|\Z)|~~~[\s\S]*?(?:~~~|\Z)|(?m:^[ \t]*>[^\n]*(?:\n|$))')


def structure(text):
    masked = list(text)
    excluded = []
    for match in EXCLUDED.finditer(text):
        kind = 'quote' if match.group().lstrip().startswith('>') else 'fenced_code'
        excluded.append({'start':match.start(),'end':match.end(),'kind':kind})
        for i in range(match.start(),match.end()):
            if masked[i] not in '\r\n':masked[i]=' '
    view=''.join(masked)
    spans=[]
    # Paragraph boundaries are never bridged. Long unpunctuated text is retained as one unit.
    for paragraph in re.finditer(r'[^\n]+(?:\n(?![ \t]*\n)[^\n]+)*',view):
        for sentence in re.finditer(r'.+?(?:[。！？!?]+|\.(?=\s|$)|$)',paragraph.group(),re.S):
            start,end=paragraph.start()+sentence.start(),paragraph.start()+sentence.end()
            while start<end and view[start].isspace():start+=1
            while end>start and view[end-1].isspace():end-=1
            if start<end:
                # Historical whitespace-flattened tables may be one enormous sentence.
                # Cover every character with overlapping bounded units, never truncate.
                cursor=start
                while cursor<end:
                    stop=min(end,cursor+1000)
                    if stop<end:
                        boundary=view.rfind(' ',cursor+700,stop)
                        if boundary>cursor:stop=boundary
                    spans.append({'start':cursor,'end':stop,'paragraph':paragraph.start()})
                    if stop==end:break
                    cursor=stop-150
    return {'text':view,'segments':spans,'excluded_spans':excluded,
            'quality':{'original_characters':len(text),'analysis_characters':sum(not c.isspace() for c in view),
                       'excluded_characters':sum(s['end']-s['start'] for s in excluded),
                       'has_paragraph_boundaries':'\n' in text,
                       'note':'保留完整输入；代码块与Markdown引用只从判别视图屏蔽；超长单句按1000字符覆盖分片、重叠150字符，历史段落无法恢复'}}


def windows(structured):
    spans=structured['segments']
    for index,first in enumerate(spans):
        # At most three adjacent sentences, max1200 chars; a longer single sentence stays whole.
        end=first['end']
        for following in spans[index+1:index+3]:
            if following['paragraph']!=first['paragraph'] or following['end']-first['start']>1200:break
            end=following['end']
        yield first['start'],end,structured['text'][first['start']:end]


def duplicate_groups(records, distances, threshold=.97):
    """Prototype-anchored grouping avoids transitive chain merging.

    Negation and numeric differences prevent collapse even at high lexical similarity.
    Groups are tentative, never deletions or assertions of common authorship.
    """
    texts=[r['content'] for r in records]
    signatures=[(tuple(re.findall(r'\b\d+(?:\.\d+)?\b',t)),
                 tuple(re.findall(r'\b(?:not|never|without|cannot|no)\b|不|没|无',t.lower()))) for t in texts]
    assigned=set();groups=[]
    for i,r in enumerate(records):
        if i in assigned:continue
        members=[i];assigned.add(i)
        for j in range(i+1,len(records)):
            if j in assigned or signatures[i]!=signatures[j]:continue
            ratio=min(len(texts[i]),len(texts[j]))/max(len(texts[i]),len(texts[j]),1)
            if ratio>=.85 and distances[i,j]<=1-threshold:
                members.append(j);assigned.add(j)
        if len(members)>1:
            groups.append({'representative_id':r['id'],'records':[records[j]['id'] for j in members],
                           'minimum_similarity_to_representative':float(min(1-distances[i,j] for j in members)),
                           'sources':sorted({records[j]['source'] for j in members})})
    return {'version':VERSION,'similarity_threshold':threshold,'groups':groups,
            'duplicate_count':sum(len(g['records'])-1 for g in groups),
            'note':'仅候选间的词面近重复诊断，保留所有记录。数字或否定不同不合并；组内按代表记录直接比较，避免相似链传递。非转载事实认定。'}
