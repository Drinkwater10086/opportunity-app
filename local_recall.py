"""Optional local semantic suggestions; never replace opportunity decisions."""
import numpy as np
import local_embeddings

VERSION='semantic-related-records-v1'


def suggestions(records,judgments,direction,config):
    threshold=config.get('semantic_recall_threshold',.85)
    base={'version':VERSION,'threshold':threshold,'items':[],'evaluated_count':0,'matched_count':0,'maximum_shown':50}
    if not config.get('semantic_recall',False):return {**base,'status':'disabled'}
    eligible=[r for r in records if not judgments[r['id']]['opportunity'] and not judgments[r['id']]['excluded']
              and all(judgments[r['id']][key] for key in ('quality','real_need','context','ai_core','feasible'))]
    if not eligible:return {**base,'status':'no_eligible_records'}
    scope=config.get('direction_terms','').strip() or direction
    queries=[f'{scope}：用户在实际工作中遇到处理困难，需要改进现有流程。',
             f'{scope}: a user needs a practical solution to a recurring task or a gap in the current workflow.']
    vectors,metadata=local_embeddings.embed(queries+[judgments[r['id']]['analysis_text'] for r in eligible])
    scores=np.clip(vectors[2:]@vectors[:2].T,-1,1).max(axis=1)
    found=[{'record_id':r['id'],'similarity':round(float(score),6),'failed_checks':judgments[r['id']]['failed_checks']}
           for r,score in zip(eligible,scores) if score>=threshold]
    found.sort(key=lambda item:(-item['similarity'],item['record_id']))
    return {**base,'status':'complete','evaluated_count':len(eligible),'matched_count':len(found),'items':found[:50],
            'model_id':metadata.get('model_id'),'model_revision':metadata.get('revision'),'query_texts':queries,
            'role':'扩展检索线索，独立列出；未通过原有筛选条件的记录不计入机会、聚类或价值排序'}
