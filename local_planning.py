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
VERSION='evidence-planning-template-v1'


def initial_drafts(result):
    """Immutable initial hypotheses, generated once for a new experiment."""
    drafts={}
    for cluster in result['clusters']:
        representative=cluster.get('representative_id')
        ordered=([representative] if representative in cluster['records'] else [])+[rid for rid in cluster['records'] if rid!=representative]
        samples=ordered[:3]
        def excerpts(field):
            lines=[]
            for rid in samples:
                value=result['judgments'][rid].get(field,'').strip()
                if value:lines.append(f'{rid}原文线索：\n> '+value.replace('\n','\n> '))
            return '\n\n'.join(lines) or '当前证据不足，待核对来源；未推断具体人员或业务。'
        function=cluster.get('function') or '当前功能'
        plan=Plan(
            target_users='候选用户/场景线索，须回查确认，不能当作已访谈用户。\n'+excerpts('user_evidence'),
            pain_points='待验证痛点，以下为原文线索，不是确认结论。\n'+excerpts('need_evidence'),
            core_features=f'初始范围假设：围绕“{cluster["name"]}”实现{function}的最小验证流程。\n'
                          '1. 接收一条与原文相符的输入，校验必填信息。\n2. 展示候选处理结果与来源记录，允许确认或纠正。\n'
                          '3. 保存处理状态并导出结果。具体业务字段和操作边界须按原文补充，未自动推断。',
            technical_route='技术候选仅整理原文已出现的实现线索；不是对接口、许可或效果的确认。\n'+excerpts('feasibility_evidence')+
                            '\n\n建议验证路径（假设）：先用匿名样本验证输入/输出，再封装处理接口与状态存储，最后接入页面。'
                            '确认组件许可、资源和失败处理后再定选型，不因出现API或模型词就认定成熟可用。',
            schedule='示例估计（待验证假设，不是交付承诺）：证据与范围核对2个工作日，最小原型5个工作日，'
                     '异常与回归验证3个工作日，共10个工作日。实际工期须按数据、接口授权及团队能力重新估计。',
            subtasks='建议分工，尚未分配真实人员：\n1. 需求研究：核对原文用户、问题及已有解决办法，界定是否需要AI。\n'
                     '2. 技术实现：明确输入输出、实现最小处理链路、记录失败原因。\n'
                     '3. 测试与决策：执行正常/缺失/重复输入及依赖不可用案例，回查结果来源后决定是否继续。',
            resources='当前研究工具的本地分析不调用外部生成式模型API；目标方案的接口、模型、部署、人工与运行成本尚未实测。'
                      '建议先用现有电脑做单条原型，记录内存、耗时和调用量，再估算预算。角色建议为需求研究、实现和验证/决策，未冒充已配备人员。',
            validation='初始验收方案（待团队确认）：\n1. 每次输出保留输入、处理版本及来源编号，可回查原文。\n'
                       '2. 正常输入、缺失字段、重复提交、组件不可用均有明确预期与实际记录。\n'
                       '3. 不将技术词共现、规则分或稳定性当准确率；未有独立真值时不填准确率/F1或效果提升。\n'
                       '4. 核对是否解决原文问题，再由决策者决定投入；尚未宣称通过。'
        ).model_dump()
        drafts[cluster['id']]={'generator_version':VERSION,'plan':plan,'origin':'program_initial_draft',
                               'sample_ids':samples,'member_count':len(cluster['records']),
                               'note':'代表记录优先，其余按簇内顺序，最多整理3条线索；非统计代表性抽样，全体来源仍在证据部分。建议是未验证假设，原实验不覆盖。'}
    return drafts


def render(batch_id,run_id,cluster,result,plan,revision=None,origin=None,generator_version=None):
    rows={r['id']:r for r in result['input_records']}
    text=[f"# {cluster['name']}",'',f'采集批次：{batch_id}；分析实验：{run_id}',
          f"策划修订：{revision or ('未保存，程序初始草案' if origin=='program_initial_draft' else '未保存，使用待填写模板')}",
          f"初稿生成方法：{generator_version or '该历史实验未保存程序初稿版本'}",'',
          '> 本文包含程序整理或已保存的计划。建议均为待验证假设，不是访谈结论、市场预测或交付承诺。','']
    if origin=='program_initial_draft':
        text.extend(['初始草案最多整理3条线索（代表记录优先），非统计代表性抽样；下方原文证据列出主题全体成员。',''])
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
