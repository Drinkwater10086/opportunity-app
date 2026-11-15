"""Bounded lexical negation and content-intent rules; not full language understanding."""
import re

VERSION='negation-and-tutorial-v1'
NEGATIVE_PREFIX=re.compile(
    r"(?:\b(?:(?:do|does|did|would|should|could|can)\s+not|(?:don|doesn|didn|wouldn|shouldn|couldn|can)['’]t|no\s+longer|never|not|no)"
    r"(?:\s+(?:really|actually|currently|have|face|experience|any|an?|the))*\s*$|(?:不再|并不|不|无需|无须|没有必要|没必要)\s*$)",re.I)
TUTORIAL=re.compile(r'本教程|纯教程|入门教程|教程演示|本文将(?:教|介绍)|\b(?:this tutorial|pure tutorial|in this tutorial|this guide (?:shows|explains)|learn how to|step.by.step tutorial|beginner.s guide)\b',re.I)
PERSONAL_PROBLEM=re.compile(
    r'(?:(?:我们|我|团队)[^。！？\n]{0,100}(?:无法|失败|困难|耗时|遇到))|'
    r'\b(?:I|we|our team|my team)\b[^.!?\n]{0,100}\b(?:cannot|can.t|unable|struggl\w*|failed|failing|problem)\b',re.I)


def negated(text,start):
    # Immediate grammatical prefix, not any "not" elsewhere in a paragraph.
    return bool(NEGATIVE_PREFIX.search(text[max(0,start-70):start]))


def first_asserted(text,pattern):
    return next((m for m in re.finditer(pattern,text,re.I) if not negated(text,m.start())),None)


def span(match):
    return {'start':match.start(),'end':match.end(),'text':match.group()} if match else None


def tutorial_status(text):
    cue=next((m for m in TUTORIAL.finditer(text) if not negated(text,m.start())),None)
    problem=PERSONAL_PROBLEM.search(text)
    return {'exclude':bool(cue and not problem),'cue':span(cue),'personal_problem':span(problem),
            'note':'教程自述且无第一人称实际困难时排除；异常表达规则仍可能误判，非完整语义理解'}
