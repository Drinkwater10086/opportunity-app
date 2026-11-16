'use strict';
const $=id=>document.getElementById(id);
const node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
const statuses={queued:'等待',running:'运行中',complete:'完成',failed:'失败'};
let selected='',runId='',timer=null,epoch=0;
async function api(url,body){const r=await fetch(url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let d;try{d=await r.json();}catch{throw Error('服务器未返回有效响应，请检查后端是否运行');}if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'参数无效或登录已过期，请检查输入或返回主页登录');return d;}
function link(text,url){const a=node('a',text);a.href=url;a.className='link';return a;}
const factorNames={quality:'正文质量',relevant:'方向相关性',real_need:'需求线索',context:'使用场景',ai_core:'AI关联性',feasible:'实现线索',classified:'功能分类'};
const reasonNames={quality:'正文过短',relevant:'方向词未命中',real_need:'无肯定需求线索',context:'无场景词',ai_core:'AI与需求关系不足或被否定',feasible:'无技术实现线索',classified:'功能标签未命中',exclude:'推广排除词',tutorial_content:'教程内容，未发现实际困难',job_posting:'结构化招聘广告，未发现应用处理诉求',compiled_background:'文献或资讯汇编，仅作背景',below_threshold:'评分低于阈值',technical_context_only:'仅为技术背景'};
function disclosure(title){const d=node('details');d.append(node('summary',title));return d;}
function recordEvidence(record,j){
 const body=node('div');if(!j){body.append(node('p','此记录没有保存的判别结果，请核查实验完整性。'));return body;}
 body.append(node('p',j.reason));
 try{const url=new URL(record.url);if(['https:','http:'].includes(url.protocol))body.append(link('查看公开来源',url.href));}catch{}
 if(j.score_detail){const s=disclosure(`评分依据：${j.score_kind}；硬条件完整性 ${j.rule_completeness}`);for(const [key,f] of Object.entries(j.score_detail.components)){
  s.append(node('p',`${factorNames[key]??key}：强度 ${f.value} × 权重 ${f.weight} = ${f.contribution}；${f.reason}`));
  for(const e of f.evidence??[])s.append(node('p',`原文[${e.start},${e.end})：${e.text}`));
 }s.append(node('p',`${j.score_detail.cap_reason??'旧方法无附加限分'}；最终分数 ${j.confidence}。${j.score_detail.note}`));body.append(s);}
 if(j.selected_context)body.append(node('p',`判别上下文[${j.selected_context.start},${j.selected_context.end})：${j.selected_context.text}`));
 if(j.content_context){const c=j.content_context;for(const e of c.denied_need_spans??[])body.append(node('p',`否定需求词[${e.start},${e.end})：${e.text}`));for(const e of c.record_tentative_need_spans??c.tentative_need_spans??[])body.append(node('p',`推测性需求词[${e.start},${e.end})：${e.text}（未作为肯定需求）；前文：${e.prefix_text??'见所选上下文'}`));for(const e of c.record_dependency_need_spans??[])body.append(node('p',`任务依赖引用[${e.start},${e.end})：${e.text}（未作为需求证据）`));if(c.tutorial?.cue)body.append(node('p','教程线索：'+c.tutorial.cue.text));}
 if(j.content_context?.job_posting){const g=j.content_context.job_posting;const d=disclosure(`招聘内容检查：${g.exclude?'作为岗位广告排除':'未因招聘内容排除'}`);for(const [key,e] of Object.entries(g.signals))if(e)d.append(node('p',`${key} · 原文[${e.start},${e.end})：${e.text}`));if(g.title_cue)d.append(node('p','标题线索：'+g.title_cue.text));if(g.user_task)d.append(node('p','用户处理诉求：'+g.user_task.text));d.append(node('p',g.note));body.append(d);}
 if(j.content_context?.compilation){const g=j.content_context.compilation,d=disclosure(`内容角色：${({academic_compilation:'论文汇编',news_compilation:'资讯汇编',unclassified:'未命中汇编规则'})[g.role]??g.role}；${g.exclude?'仅作背景':'未因此排除'}`);for(const [key,v] of Object.entries(g.signals))if(v.first)d.append(node('p',`${key} · ${v.count}处；首处原文[${v.first.start},${v.first.end})：${v.first.text}`));if(g.title_cue)d.append(node('p','标题线索：'+g.title_cue.text));if(g.user_request_exception)d.append(node('p','标题与正文匹配实际业务处理请求，保留参与后续判别的资格。'));d.append(node('p',g.note));body.append(d);}
 const traces=disclosure('全部判别证据与处理说明');for(const [key,span] of Object.entries(j.evidence_spans??{}))if(span)traces.append(node('p',`${key} · 原文[${span.start},${span.end})：${span.text}`));
 if(j.data_quality)traces.append(node('p',`分析字符 ${j.data_quality.analysis_characters} · 屏蔽代码/引用/隐藏内容 ${j.data_quality.excluded_characters} 字符；${j.data_quality.note}`));body.append(traces);
 const original=disclosure('完整清洗文本');let loaded=false;original.ontoggle=()=>{if(original.open&&!loaded){loaded=true;original.append(node('pre',record.content));}};body.append(original);return body;
}
function evidenceInspector(result){
 const root=disclosure(`查询 ${result.record_count} 条记录与原文证据`);root.id='evidence-inspector';
 const search=node('input');search.type='search';search.placeholder='记录编号、标题或原文关键词';search.setAttribute('aria-label','搜索记录');
 const filter=node('select');filter.setAttribute('aria-label','记录筛选');for(const [value,title] of [['all','全部记录'],['positive','候选机会'],['negative','未通过记录']]){const o=node('option',title);o.value=value;filter.append(o);}filter.value=result.candidate_count?'positive':'all';
 const status=node('p'),list=node('div'),controls=node('div'),previous=node('button','上一页'),next=node('button','下一页');status.setAttribute('role','status');controls.className='toolbar';controls.append(previous,next);root.append(search,filter,status,list,controls);
 let page=0,initialized=false,debounce=null,stageIds=new Set();const size=20;
 function render(){initialized=true;const query=search.value.trim().toLowerCase();const rows=result.input_records.filter(record=>{
  const j=result.judgments[record.id];return (filter.value==='all'||(filter.value==='stage'?stageIds.has(record.id):filter.value==='positive'?j?.opportunity:!j?.opportunity))&&(!query||[record.id,record.title,record.content,record.source].some(v=>String(v??'').toLowerCase().includes(query)));
 });const pages=Math.max(1,Math.ceil(rows.length/size));page=Math.min(page,pages-1);list.replaceChildren();
 for(const record of rows.slice(page*size,(page+1)*size)){const j=result.judgments[record.id],article=node('article');article.dataset.recordId=record.id;article.append(node('h3',`${record.id} · ${record.title}`),node('p',j?`${j.opportunity?'候选机会':'未通过'} · 机会证据分 ${j.confidence} · ${record.source}`:'无判别结果'));
  const d=disclosure('查看本条证据');let loaded=false;d.ontoggle=()=>{if(d.open&&!loaded){loaded=true;d.append(recordEvidence(record,j));}};article.append(d);list.append(article);
 }
 status.textContent=rows.length?`匹配 ${rows.length} 条；第 ${page+1}/${pages} 页，显示 ${page*size+1}–${Math.min(rows.length,(page+1)*size)} 条。所有记录可查询或导出。`:'没有匹配记录。';previous.disabled=page===0;next.disabled=page>=pages-1;
 }
 root.ontoggle=()=>{if(root.open&&!initialized)render();};search.oninput=()=>{clearTimeout(debounce);debounce=setTimeout(()=>{page=0;render();},150);};filter.onchange=()=>{page=0;render();};previous.onclick=()=>{page--;render();};next.onclick=()=>{page++;render();};
 return {element:root,focusIds(ids,label){stageIds=new Set(ids);let option=Array.from(filter.options).find(o=>o.value==='stage');if(!option){option=node('option');option.value='stage';filter.append(option);}option.textContent='本环节排除：'+label;root.open=true;search.value='';filter.value='stage';page=0;render();root.scrollIntoView({block:'start'});},focus(id){root.open=true;search.value=id;filter.value='all';page=0;render();const entry=Array.from(list.children).find(n=>n.dataset.recordId===id);if(entry){entry.querySelector('details').open=true;entry.scrollIntoView({block:'start'});}}};
}
function evaluationDetails(result){
 const root=disclosure('实验评价、方法与限制');root.id='technical-evaluation';root.append(node('p',result.representation),node('p',`方法 ${result.version} · scikit-learn ${result.sklearn_version} · 随机种子 ${result.seed}`));
 const params=disclosure('本次实验参数（上方表单仅用于下一次运行）');params.append(node('pre',JSON.stringify(result.config,null,2)));root.append(params);
 if(result.embedding_metadata){const e=result.embedding_metadata;root.append(node('p',`${e.model_id} · ${e.revision} · ${e.license} · ${e.coverage.reduce((n,c)=>n+c.length,0)}个分片 · 未截断：${!e.truncated}`),node('p',e.note));}
 const why=disclosure('筛选原因（可重叠）');for(const [key,count] of Object.entries(result.exclusions))why.append(node('p',`${reasonNames[key]??key}：${count}条`));why.append(node('p','规则只提供证据线索，不能证明需求真实、AI必要性或市场价值。'));root.append(why);
 if(result.duplicate_diagnostics){const d=result.duplicate_diagnostics,duplicates=disclosure('近重复诊断');duplicates.append(node('p',`${d.groups.length}个组，${d.duplicate_count}条重复关联；正式规模分按记录条数计算。`),node('p',d.note));for(const g of d.groups)duplicates.append(node('p',`${g.representative_id}：${g.records.join('、')}`));root.append(duplicates);}
 root.append(node('p',`成员编号完整性：${result.evaluation.structure_valid?'通过':'未通过'}`));
 for(const [key,title] of [['primary','当前表示空间'],['baseline','TF-IDF基线'],['primary_in_lexical_space','主分组在完整原文词面空间'],['baseline_in_full_text_space','基线分组在完整原文词面空间'],['baseline_in_primary_space','基线分组在主表示空间']]){
  const e=result.evaluation[key];if(!e)continue;const view=disclosure(title);view.append(node('p',`${e.cluster_count}簇 · 单记录簇 ${e.singleton_count} · 轮廓系数 ${e.silhouette===null?'无法计算':e.silhouette.toFixed(4)} · 最大簇 ${(100*e.largest_cluster_fraction).toFixed(1)}%`),node('p',e.reason));for(const w of e.warnings??[])view.append(node('p',w));root.append(view);
 }
 if(result.evaluation.semantic_threshold_grid){const grid=disclosure('E5固定阈值网格（未自动择优）');for(const e of result.evaluation.semantic_threshold_grid)grid.append(node('p',`距离${e.distance_threshold}：${e.cluster_count}簇，单例${e.singleton_count}，最大簇${(100*e.largest_cluster_fraction).toFixed(1)}%`));root.append(grid);}
 if(result.evaluation.value_diagnostics){const v=result.evaluation.value_diagnostics,d=disclosure('价值权重敏感性（不改变正式排名）');d.append(node('p',v.note));for(const row of v.weight_grid)d.append(node('p',`来源覆盖权重 ${(100*row.coverage_weight).toFixed(1)}%，记录规模 ${(100*row.scale_weight).toFixed(1)}%；最高同分主题：${row.top_ids.join('、')}`));root.append(d);}
 const sensitivity=disclosure('规则阈值、聚类敏感性与消融');for(const e of result.evaluation.threshold_sensitivity)sensitivity.append(node('p',`机会阈值${e.threshold}：${e.candidate_count}条候选`));for(const e of result.evaluation.sensitivity)sensitivity.append(node('p',`聚类距离${e.distance_threshold.toFixed(2)}：${e.cluster_count}簇，共同输入ARI ${e.ari===null?'样本不足':e.ari.toFixed(4)}`));for(const [key,count] of Object.entries(result.evaluation.ablation))sensitivity.append(node('p',`移除${reasonNames[key]??key}门槛：${count}条（保留原分数及阈值）`));root.append(sensitivity,node('p',result.evaluation.note),node('p',result.score_formula));return root;
}
function report(result,base){
 const box=$('result');box.replaceChildren(node('h2','分析结论'),node('p',result.conclusion));const cards=node('div');cards.className='cards';for(const [title,value] of [['采集记录',result.record_count],['候选机会',result.candidate_count],['机会主题',result.clusters.length]]){const c=node('div');c.className='stat';c.append(node('strong',String(value)),node('span',title));cards.append(c);}box.append(cards);
 box.append(node('p','机会证据分表示规则支持强度；主题价值分用于本批次相对排序，两者均不是准确率或市场规模。'));
 if(result.evaluation.value_diagnostics?.all_scores_equal)box.append(node('p','所有主题的正式价值分相同，当前两个评分维度无法区分优先价值；请结合原文证据决策，不将展示先后当作优劣。'));
 const downloads=node('div');downloads.className='toolbar';for(let n=1;n<=4;n++)downloads.append(link(`result${n}.csv`,base+`/result${n}.csv`));downloads.append(link('证据与实验参数',base+'/evidence.json'));box.append(downloads);
 if(result.direction_scope){const s=result.direction_scope,labels={explicit:'仅显式方向词',office_profile:'办公方向词典',industry_profile:'行业方向词典',literal:'原方向词，未扩展'},d=disclosure(`本次方向范围：${labels[s.mode]??s.mode}${s.profile?' / '+s.profile:''}`);d.append(node('p','配置词：'+s.configured_terms.join('、')),node('p','扩展词：'+(s.expanded_terms.join('、')||'无')),node('p',s.note));box.append(d);}
 const sourceRecords=new Map(result.input_records.map(r=>[r.id,r]));
 const inspector=evidenceInspector(result);
 if(result.evaluation.screening_flow){const f=result.evaluation.screening_flow,flow=disclosure('查看筛选过程与流失记录');if(!result.candidate_count)flow.open=true;flow.append(node('p',f.note));
  if(!f.matches_decisions)flow.append(node('p','筛选统计与已保存机会标记不一致，请核查本次实验。'));
  for(const stage of f.stages){if(!stage.entered)continue;const line=node('p',`${stage.label}：进入${stage.entered}条，排除${stage.removed}条，保留${stage.remaining}条。`);if(stage.removed){const b=node('button',`查看${stage.label}排除的${stage.removed}条`);b.onclick=()=>inspector.focusIds(stage.removed_ids,stage.label);line.append(b);}flow.append(line);}const inactive=f.stages.filter(stage=>!stage.entered).length;if(inactive)flow.append(node('p',`后续${inactive}个环节的累计保留数均为0；完整统计可在“证据与实验参数”中查看。`));box.append(flow);
 }
 if(!result.candidate_count&&result.record_count>0&&result.exclusions.relevant===result.record_count)box.append(node('p','本批次全部记录未命中当前研究方向或场景词。采集检索词与研究方向分别生效，可核对方向词，或回主页用贴近研究方向的检索词新建采集批次。'));
 box.append(node('h2','机会主题与优先级'));
 if(!result.clusters.length)box.append(node('p','当前没有记录同时满足方向、需求、AI与可落地证据及评分阈值。可在下方查询记录查看具体原因；空结果不会生成虚构机会。'));
 for(const c of result.clusters){const section=node('article');section.dataset.themeId=c.id;section.append(node('h3',`${c.priority}. ${c.name}`),node('p',`样本内价值分 ${c.score.toFixed(2)} · ${c.count}条记录 · ${c.function} / ${c.industry} · ${c.sources.join('、')}`));
  if(c.name_features?.length)section.append(node('p','代表原文标题：'+(sourceRecords.get(c.representative_id)?.title??c.representative_id)));
  if((c.same_score_count??1)>1)section.append(node('p',`与另外${c.same_score_count-1}个主题同分；当前顺序按簇编号固定展示，不表示价值高低差异。`));
  section.append(node('p','查看构成这个主题的原始记录：'));const members=node('div');members.className='toolbar';for(const id of c.records){const button=node('button',id);button.setAttribute('aria-label',`查看记录 ${id}`);button.onclick=()=>inspector.focus(id);members.append(button);}section.append(members,link('导出立项策划 Markdown',base+`/proposal/${c.id}.md`));
  const detail=disclosure('主题命名与评分依据');detail.append(node('p',`代表记录 ${c.representative_id}；${c.name_method??'历史主题命名方法见实验参数'}。`),node('p',`近重复组数 ${c.unique_evidence_count??c.count}；调整分 ${c.duplicate_adjusted_score??c.score}仅作对照；正式分按记录规模计算。`));for(const feature of c.name_features??[]){detail.append(node('p',`命名场景“${feature.label}”：${feature.support_count}/${feature.record_count}条支持`));for(const e of feature.evidence)detail.append(node('p',`${e.record_id} · 原文[${e.start},${e.end})：${e.text}`));}section.append(detail);planEditor(section,base,c.id);box.append(section);
 }
 box.append(inspector.element);const e=result.evaluation.primary;
 if(result.candidate_count<2)box.append(node('p','候选少于2条，轮廓系数无法计算；这是评价样本条件，不代表采集或程序运行失败。'));
 else if(e)box.append(node('p',`聚类诊断：${e.cluster_count}簇，其中${e.singleton_count}个单记录簇。${(e.warnings??[]).join('；')}`));
 box.append(evaluationDetails(result));
}

function planEditor(container,base,clusterId){
 const details=node('details');details.append(node('summary','编辑立项策划（计划与原文分开保存）'));container.append(details);let loaded=false;
 details.ontoggle=async()=>{if(!details.open||loaded)return;loaded=true;const status=node('p','读取策划修订…');details.append(status);try{
  const saved=await api(base+'/plans/'+encodeURIComponent(clusterId)),form=node('form'),fields={};
  const labels={target_users:'目标用户',pain_points:'核心痛点',core_features:'核心功能',technical_route:'技术路线',schedule:'实施周期',subtasks:'子任务分解',resources:'资源与成本',validation:'验证与验收标准'};
  for(const [key,title] of Object.entries(labels)){const label=node('label',title),input=node('textarea');input.value=saved.plan[key]??'';input.maxLength=['target_users','schedule','resources'].includes(key)?4000:8000;label.append(input);fields[key]=input;form.append(label);}
  const button=node('button','保存策划修订');button.type='submit';form.append(button);details.append(form);status.textContent=(saved.origin==='program_initial_draft'?'当前为程序初始草案，建议工期、分工和验收方案均待验证。':saved.origin==='legacy_blank'?'此历史实验未保存程序初稿，可填写计划或新建本地实验。':'当前为已保存修订。')+'保存时新增修订记录，不改变原分析证据。';
  if(saved.note)details.append(node('p',saved.note));
  form.onsubmit=async e=>{e.preventDefault();button.disabled=true;try{const result=await api(base+'/plans/'+encodeURIComponent(clusterId),Object.fromEntries(Object.entries(fields).map(([key,input])=>[key,input.value])));status.textContent=`已保存 ${result.id}；上方导出链接将包含本次修订。`;}catch(error){status.textContent=error.message;}finally{button.disabled=false;}};
 }catch(error){status.textContent=error.message;loaded=false;}};
}

function comparisonControl(rows,base,currentId){
 const options=rows.filter(r=>r.id!==currentId&&r.status==='complete');if(!options.length)return;
 const panel=node('section'),select=node('select'),button=node('button','比较已保存实验'),output=node('p');
 select.setAttribute('aria-label','对照实验');for(const r of options){const o=node('option',`${r.id} · ${r.created_at}`);o.value=r.id;select.append(o);}
 panel.append(node('h3','同批次实验对比'),select,button,output);$('result').append(panel);
 button.onclick=async()=>{button.disabled=true;try{const r=await api(base+'/compare/'+encodeURIComponent(select.value));output.textContent=`从当前实验到所选实验：候选 ${r.left_candidates} → ${r.right_candidates}，新增 ${r.added_ids.join('、')||'无'}，移除 ${r.removed_ids.join('、')||'无'}；共同 ${r.common_candidates} 条上的 ARI：${r.ari_on_common_candidates===null?'无法计算':r.ari_on_common_candidates.toFixed(4)}。${r.note}`;}catch(e){output.textContent=e.message;}finally{button.disabled=false;}};
}

async function poll(token){if(token!==epoch||!runId)return;const batch=selected,id=runId,base=`/api/batches/${encodeURIComponent(batch)}/local-runs/${encodeURIComponent(id)}`;try{const run=await api(base);if(token!==epoch||id!==runId)return;$('notice').textContent=`${id}：${statuses[run.status]??run.status}${run.error?' · '+run.error:''}`;const active=['queued','running'].includes(run.status);$('start').disabled=active;if(active){timer=setTimeout(()=>poll(token),1500);return;}if(run.status==='complete')report(run.result,base);else $('result').replaceChildren(node('p',run.error||'未完成'));const rows=await history(id);if(run.status==='complete'&&token===epoch&&rows)comparisonControl(rows,base,id);}catch(e){if(token===epoch){$('notice').textContent=e.message;$('start').disabled=false;}}}
async function history(preferred){const batch=selected,rows=await api(`/api/batches/${encodeURIComponent(batch)}/local-runs`);if(selected!==batch)return;$('runs').replaceChildren();for(const r of rows){const option=node('option',`${r.created_at} · ${r.id} · ${statuses[r.status]??r.status}`);option.value=r.id;$('runs').append(option);}if(preferred&&rows.some(r=>r.id===preferred))$('runs').value=preferred;return rows;}
async function selectBatch(){$('start').disabled=true;epoch++;clearTimeout(timer);selected=$('batch').value;runId='';$('result').replaceChildren(node('p','正在读取批次…'));if(!selected)return;const token=epoch;try{const data=await api(`/api/batches/${encodeURIComponent(selected)}`);if(token!==epoch)return;$('batch-info').textContent=`${data.batch.direction} · ${data.records.length} 条 · ${data.batch.status}`;$('start').disabled=data.batch.status!=='collected'||!data.records.length;$('notice').textContent='';const rows=await history();if(token!==epoch)return;if(rows?.length){runId=rows[0].id;await poll(token);}else $('result').replaceChildren(node('p','尚无本地实验。'));}catch(e){$('notice').textContent=e.message;}}
$('batch').onchange=selectBatch;$('runs').onchange=()=>{epoch++;clearTimeout(timer);runId=$('runs').value;poll(epoch);};
$('run-form').onsubmit=async e=>{e.preventDefault();if(!selected)return;const token=++epoch;clearTimeout(timer);$('start').disabled=true;try{const r=await api(`/api/batches/${encodeURIComponent(selected)}/local-runs`,{threshold:Number($('threshold').value),score_method:$('score-method').value,distance_threshold:Number($('distance').value),dimensions:Number($('dimensions').value),vector_method:$('vector-method').value,semantic_distance_threshold:Number($('semantic-distance').value),coverage_weight:Number($('coverage').value),scale_weight:Number($('scale').value),direction_terms:$('direction-terms').value});if(token!==epoch)return;runId=r.id;$('result').replaceChildren(node('p','本地分析中…'));await poll(token);}catch(error){$('notice').textContent=error.message;$('start').disabled=false;}};
(async()=>{try{const rows=await api('/api/batches');for(const b of rows){const o=node('option',`${b.id} · ${b.direction} · ${b.count}条`);o.value=b.id;$('batch').append(o);}const requested=new URLSearchParams(location.search).get('batch');if(rows.some(b=>b.id===requested))$('batch').value=requested;if(!rows.length){$('notice').textContent='请返回主页先采集数据';$('start').disabled=true;}else await selectBatch();}catch(e){$('notice').textContent=e.message;}})();
