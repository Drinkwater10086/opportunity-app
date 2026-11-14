"""Explicit content conversion; no execution, remote assets, or inferred transcripts."""
from html.parser import HTMLParser
from html import unescape
import re
import xml.etree.ElementTree as ET


class SafeText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.ignored = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script','style','iframe','template'):
            self.ignored += 1
        elif not self.ignored and tag in ('p','br','div','li','tr','h1','h2','h3','pre'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script','style','iframe','template'):
            self.ignored = max(0, self.ignored-1)
        elif not self.ignored and tag in ('p','div','li','tr','pre'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def text(value, kind='text'):
    if not isinstance(value, str):
        raise ValueError('正文必须是字符串')
    if kind == 'html':
        parser = SafeText(); parser.feed(value)
        return unescape(''.join(parser.parts)).strip()
    if kind in ('text','markdown'):
        return value.strip()
    if kind in ('srt','vtt'):
        # Only supplied transcript text; never invent speech from title/description.
        lines = [line for line in value.splitlines() if not re.match(r'^\s*(?:WEBVTT|\d+\s*$|\d{1,2}:\d{2}.*-->).*', line)]
        return text('\n'.join(lines), 'html')
    raise ValueError('不支持的正文格式；图片、音频、视频和PDF不能直接当作正文，须另行取得可用文本')


def feed_entries(payload):
    """RSS 2.0 or Atom; reject DTD/entities rather than resolve untrusted XML."""
    if len(payload) > 4_000_000:
        raise ValueError('订阅响应超过4MB，未截断')
    if b'<!DOCTYPE' in payload.upper() or b'<!ENTITY' in payload.upper():
        raise ValueError('订阅包含不允许的DTD或实体声明')
    root = ET.fromstring(payload)
    if root.tag == 'rss':
        return [{'title':item.findtext('title') or '', 'url':item.findtext('link') or '',
                 'body':item.findtext('description') or '', 'body_format':'html',
                 'published':item.findtext('pubDate'), 'updated':None,
                 'date_basis':'item.pubDate'} for item in root.findall('./channel/item')], 'rss'
    ns = '{http://www.w3.org/2005/Atom}'
    if root.tag == ns+'feed':
        rows=[]
        for item in root.findall(ns+'entry'):
            body=item.find(ns+'summary')
            if body is None: body=item.find(ns+'content')
            body_kind = body.get('type','text') if body is not None else 'text'
            if body_kind not in ('text','html'):
                raise ValueError('当前Atom仅支持text或html正文，不伪造XHTML转换')
            rows.append({'title':item.findtext(ns+'title') or '',
                         'url':next((link.get('href','') for link in item.findall(ns+'link') if link.get('rel','alternate')=='alternate'), ''),
                         'body':(body.text or '') if body is not None else '', 'body_format':body_kind,
                         'published':item.findtext(ns+'published'), 'updated':item.findtext(ns+'updated'),
                         'date_basis':'entry.published'})
        return rows,'atom'
    raise ValueError('响应不是RSS 2.0或Atom订阅')
