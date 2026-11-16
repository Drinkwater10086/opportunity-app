"""Conservative, offset-preserving analysis views. Original records are immutable."""
import re

VERSION = 'structure-and-duplicate-v4-list-boundaries'
EXCLUDED = re.compile(r'```[\s\S]*?(?:```|\Z)|~~~[\s\S]*?(?:~~~|\Z)|(?m:^[ \t]*>[^\n]*(?:\n|$))')
HTML_HIDDEN=re.compile(r'<!--[\s\S]*?(?:-->|\Z)|'
                       r'<(?P<hidden>script|style|iframe|template)\b[^>]*>[\s\S]*?(?:</(?P=hidden)\s*>|\Z)',re.I)


def structure(text):
    masked = list(text)
    regions=[]
    for pattern in (EXCLUDED,HTML_HIDDEN):
        search_text=text
        if pattern is HTML_HIDDEN:
            # Ignore literal HTML examples inside code before matching HTML.
            # Otherwise an unclosed example can consume all following prose.
            html_view=list(text)
            for region in regions:
                if region['kind']=='fenced_code':
                    for i in range(region['start'],region['end']):
                        if html_view[i] not in '\r\n':html_view[i]=' '
            search_text=''.join(html_view)
        for match in pattern.finditer(search_text):
            value=match.group().lstrip()
            kind='html_hidden' if pattern is HTML_HIDDEN else 'quote' if value.startswith('>') else 'fenced_code'
            regions.append({'start':match.start(),'end':match.end(),'kind':kind})
    excluded = []
    # Independent passes find HTML that starts inside a quoted/code region.
    # Union intervals so overlapping hidden content is not counted twice.
    for region in sorted(regions,key=lambda s:(s['start'],-s['end'])):
        if excluded and region['start']<excluded[-1]['end']:
            excluded[-1]['end']=max(excluded[-1]['end'],region['end'])
            if excluded[-1]['kind']!=region['kind']:excluded[-1]['kind']='combined_hidden'
        else:excluded.append(dict(region))
    for region in excluded:
        for i in range(region['start'],region['end']):
            if masked[i] not in '\r\n':masked[i]=' '
    view=''.join(masked)
    spans=[]
    # Do not combine unrelated bullets/headings/Markdown table rows into one claim.
    # Continuation lines within a list item remain together; offsets are unchanged.
    for paragraph in re.finditer(r'[^\n]+(?:\n(?![ \t]*\n|[ \t]*(?:[-+*][ \t]+|\d+[.)、][ \t]+|#{1,6}[ \t]+|\|))[^\n]+)*',view):
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
                       'note':'保留完整输入；代码块、Markdown引用、HTML隐藏块/注释仅从判别视图等长屏蔽；不同列表项、标题和Markdown表格行不拼接；超长单句全覆盖分片，历史已丢失段落无法恢复'}}


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
