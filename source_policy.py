"""Reviewed source restrictions, distinct from API availability and robots rules."""
REVIEWED_ON = '2026-11-10'
BLOCKED = {
    'n8n': {'name': 'n8n Community', 'terms_url': 'https://community.n8n.io/tos'},
    'make': {'name': 'Make Community', 'terms_url': 'https://community.make.com/tos'},
}
REASON = '服务条款限制自动化访问；当前研究应用不适用公开搜索引擎例外，需另行获得许可'


def issues(selected):
    return [{'source': key, **BLOCKED[key], 'reason': REASON, 'reviewed_on': REVIEWED_ON}
            for key in sorted(set(selected)) if key in BLOCKED]


def require_allowed(selected):
    restricted = issues(selected)
    if restricted:
        raise ValueError('来源已停用：'+ '、'.join(x['name'] for x in restricted)+'；'+REASON)
