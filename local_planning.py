"""Editable planning hypotheses; never fabricate customer findings or delivery dates."""
from pydantic import BaseModel, ConfigDict, Field


class Plan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target_users: str = Field(default='',max_length=4000)
    pain_points: str = Field(default='',max_length=8000)
    core_features: str = Field(default='',max_length=8000)
    technical_route: str = Field(default='',max_length=8000)
    schedule: str = Field(default='',max_length=4000)
    subtasks: str = Field(default='',max_length=8000)
    resources: str = Field(default='',max_length=4000)
    validation: str = Field(default='',max_length=8000)


LABELS = {'target_users':'目标用户','pain_points':'核心痛点','core_features':'核心功能',
          'technical_route':'技术路线','schedule':'实施周期','subtasks':'子任务分解',
          'resources':'资源与成本','validation':'验证与验收标准'}


def render(batch_id,run_id,cluster,result,plan,revision=None):
    rows={r['id']:r for r in result['input_records']}
    text=[f"# {cluster['name']}",'',f'采集批次：{batch_id}；分析实验：{run_id}',
          f"策划修订：{revision or '未保存，使用待填写模板'}",'',
          '> 本文由程序整理证据与团队填写的计划。计划是待验证假设，不是访谈结论、市场预测或交付承诺。','']
    for key,title in LABELS.items():
        text.extend([f'## {title}',plan.get(key,'').strip() or '待团队补充；当前证据不足，未自动推断。',''])
    text.extend(['## 原文证据（与上述计划分开核对）'])
    for rid in cluster['records']:
        j=result['judgments'][rid]
        text.extend([f'### {rid}',f"来源：{rows[rid]['source']} · {rows[rid]['url']}",
                     f"采集时间：{rows[rid].get('collected_at','未知')}",
                     '需求线索：', '> '+j['need_evidence'].replace('\n','\n> '),
                     '用户/场景线索：','> '+j['user_evidence'].replace('\n','\n> '),
                     '技术线索：','> '+j['feasibility_evidence'].replace('\n','\n> '),''])
    text.extend(['## 价值评分与依据',f"优先级：{cluster['priority']}；正式价值分：{cluster['score']}。",
                 f"记录：{cluster['count']}条；来源平台：{'、'.join(cluster['sources'])}。",
                 result['score_formula'],'',
                 '## 方法与限制',f"分析版本：{result['version']}；输入哈希：{result['input_sha256']}。",
                 '规则分数不是校准概率；来源自述和论文技术线索不等同需求已验证；样本内排名不等于市场规模。'])
    return '\n'.join(text)
