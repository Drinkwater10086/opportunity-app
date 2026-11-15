"""Transparent engineering rubric, not a statistically calibrated probability.

Coefficients are initial research assumptions. They require independent validation;
no source popularity or generated rationale can increase evidence strength.
"""
import re

VERSION='evidence-strength-v1'
WEIGHTS={'quality':.05,'relevant':.15,'real_need':.25,'context':.15,
         'ai_core':.20,'feasible':.15,'classified':.05}
REQUEST=r'有没有|求推荐|求助|\b(?:looking for|feature request|how can)\b'
PROBLEM=r'耗时|费时|无法|困难|痛点|重复录入|效率低|\b(?:struggl\w*|time.consuming|cannot|can.t|unable|problem)\b'
GENERIC=r'需要|希望|\b(?:needs?|needed|how do|how to)\b'


def need_signal(value):
    if re.search(REQUEST,value,re.I):return .95,'explicit_request','明确求助或寻解表达'
    if re.search(PROBLEM,value,re.I):return .85,'experienced_problem','困难或效率问题表达，仍需核实'
    if re.search(GENERIC,value,re.I):return .75,'generic_need','一般需要或希望表达，未必是现实需求'
    if value.strip():return .4,'weak_signal','仅有手动等弱需求线索'
    return 0.,'none','无需求词依据'


def strength(text,checks,hits,direct_scope_hits,scope_hits=()):
    values={key:0. for key in WEIGHTS}
    reasons={key:'未通过对应条件' for key in WEIGHTS}
    supports={key:[] for key in WEIGHTS}
    def support(match):
        return {'start':match.start(),'end':match.end(),'text':match.group()}
    def hit_support(key):
        h=hits[key]
        return {'start':h['match_start'],'end':h['match_end'],'text':h['match']} if h else None
    values['quality']=float(checks['quality']);reasons['quality']='至少30字符，仅长度门槛，不代表文本质量已验证'
    if checks['relevant']:
        values['relevant']=.95 if direct_scope_hits else .7
        reasons['relevant']='直接命中配置方向词' if direct_scope_hits else '仅命中内置办公方向扩展词'
        for term in direct_scope_hits or scope_hits:
            match=re.search(re.escape(term),text,re.I)
            if match:supports['relevant'].append(support(match))
    signal=hits['need']['match'] if hits['need'] else ''
    value,kind,reason=need_signal(signal)
    if checks['real_need']:
        values['real_need'],reasons['real_need']=value,reason
        supports['real_need']=[hit_support('need')]
    if checks['context']:
        specific=re.search(r'员工|客户|患者|学生|教师|\b(?:our team|employees?|customers?|patients?|students?|teachers?)\b',text,re.I)
        values['context']=.95 if specific else .65
        reasons['context']='命中用户角色或明确团队' if specific else '仅命中会议、文档等任务或泛场景词'
        supports['context']=[support(specific) if specific else hit_support('context')]
    if checks['ai_core']:
        distance=abs(hits['need']['match_start']-hits['ai']['match_start'])
        values['ai_core']=max(.55,.95-.4*distance/600)
        reasons['ai_core']=f'需求词与AI词相距{distance}字符；邻近不能证明AI是核心'
        supports['ai_core']=[hit_support('need'),hit_support('ai')]
    if checks['feasible']:
        named=re.search(r'\b(?:Whisper|OCR|RAG|GPT\w*)\b',text,re.I)
        mechanism=re.search(r'识别|检索|转写|分类|预测|抽取|\b(?:retrieval|transcri\w*|classif\w*|extract\w*|predict\w*)\b',text,re.I)
        values['feasible']=.9 if named else .8 if mechanism else .55
        reasons['feasible']='具体技术名称线索' if named else '具体技术机制线索' if mechanism else '仅API或model等泛技术词'
        supports['feasible']=[support(named or mechanism) if named or mechanism else hit_support('feasible')]
    values['classified']=float(checks['classified']);reasons['classified']='功能词典是否有匹配，不代表标签正确'
    components={key:{'value':round(values[key],6),'weight':weight,
                     'contribution':round(values[key]*weight,6),'reason':reasons[key],
                     'evidence':supports[key]} for key,weight in WEIGHTS.items()}
    score=round(sum(values[k]*WEIGHTS[k] for k in WEIGHTS),4)
    completeness=round(sum(WEIGHTS[k] for k in WEIGHTS if checks[k]),4)
    return score,{'version':VERSION,'components':components,'need_kind':kind,
                  'completeness':completeness,'direct_scope_hits':direct_scope_hits,
                  'note':'初始工程权重及证据强度规则，未经统计校准；分数不等于概率、准确率或真实市场需求'}
