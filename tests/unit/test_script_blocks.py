"""The script writer for rough-plan blocks (implementation plan V2), with a scripted language model."""
import json

import pytest

from strata360.edit import script as S, blocks as B


def block(i, target, dialogue=(), clip=None):
    d = [(a, b) for a, b in dialogue]
    return dict(clip=clip or f'C{i:02d}', index=i, start_utc='2026-02-19T10:00:00Z', usable=[(0.0, 60.0)], usable_s=60.0, quality=0.6, dialogue=d, dialogue_s=sum(b - a for a, b in d),
                preferred=[], min_s=2.0, max_s=60.0, natural_s=target, target_s=target)


def facts(blocks, notes=None):
    return [S.block_facts(b, None, None, notes or {'clips': {}}) for b in blocks]


@pytest.fixture
def llm(monkeypatch):
    """S.run_llm replaced: `llm.reply(obj, ...)` queues replies (dicts become the parsed JSON); `llm.calls` holds the messages sent."""
    class L:
        def __init__(self): self.q = []; self.calls = []
        def reply(self, *objs): self.q += objs
        def __call__(self, messages, model=None, max_tokens=0, temperature=0, work_dir=None, provider='vertex'):
            self.calls.append(messages); o = self.q.pop(0); return dict(text=json.dumps(o), parsed=o, model='fake')
    l = L(); monkeypatch.setattr(S, 'run_llm', l); return l


def test_facts_subtract_the_dialogue_from_the_budget():
    f = facts([block(0, 20), block(1, 20, dialogue=[(10.0, 14.0)])])
    assert (f[0]['narration_s'], f[0]['budget_words'], f[0]['has_dialogue']) == (20.0, S.budget_words(20.0), False)
    assert (f[1]['narration_s'], f[1]['dialogue_s'], f[1]['budget_words'], f[1]['has_dialogue']) == (16.0, 4.0, S.budget_words(16.0), True)
    assert f[1]['block'] == 1 and f[1]['dialogue'][0]['start_s'] == 10.0


def test_facts_accept_a_block_object():
    b = B.Block(clip='C00', index=3, start_utc='2026-02-19T10:00:00Z', usable=[(5.0, 25.0)], usable_s=20, quality=.5, dialogue=[], dialogue_s=0, preferred=[], min_s=2, max_s=20, natural_s=10, target_s=10)
    f = S.block_facts(b, None, None, {'clips': {'C00': 'a hard climb'}})
    assert f['block'] == 3 and f['clip_note'] == 'a hard climb' and f['budget_words'] == S.budget_words(10)


def test_prompt_marks_the_dialogue_gap():
    f = facts([block(0, 20), block(1, 20, dialogue=[(10.0, 14.0)])]); m = S.build_block_messages('', f, 40)
    txt = m[1]['content']
    assert '[1] 20 s' in txt and 'dialogue gap of 4.0 s' in txt and 'dialogue gap' not in txt.split('[1]')[0] and 'anchor' in m[0]['content']


def test_lines_map_to_blocks_and_totals_are_reported_per_block(llm):
    f = facts([block(0, 20), block(1, 20, dialogue=[(10.0, 14.0)])])
    llm.reply(dict(title='T', lines=[dict(block=1, anchor='after', text='Then we went on.'), dict(block=0, anchor=None, text='We set off at dawn.'), dict(block=1, anchor='before', text='A bit later.')]))
    d = S.write_block_script(f, '', 40)
    assert [(l['block'], l['anchor']) for l in d['lines']] == [(0, None), (1, 'before'), (1, 'after')] and d['lines'][0]['clip'] == 'C00'
    assert [b['words'] for b in d['blocks']] == [5, 7] and d['total_words'] == 12 and d['remaining_problems'] == [] and len(llm.calls) == 1


def test_a_dialogue_gap_is_never_written_over(llm):
    f = facts([block(0, 20, dialogue=[(10.0, 14.0)])])
    llm.reply(dict(lines=[dict(block=0, anchor=None, text='Over the dialogue.')]), dict(lines=[dict(block=0, anchor='before', text='Before it.')]))
    d = S.write_block_script(f, '', 20)
    assert len(llm.calls) == 2 and 'every line needs "anchor"' in llm.calls[1][-1]['content'] and d['lines'][0]['anchor'] == 'before' and d['remaining_problems'] == []


def test_a_missing_anchor_that_stays_is_reported_and_not_invented(llm):
    f = facts([block(0, 20, dialogue=[(10.0, 14.0)])]); bad = dict(lines=[dict(block=0, anchor='during', text='Oops.')])
    llm.reply(bad, bad); d = S.write_block_script(f, '', 20)
    assert d['lines'][0]['anchor'] is None and d['remaining_problems'][0]['block'] == 0


def test_a_block_without_dialogue_drops_a_stray_anchor(llm):
    f = facts([block(0, 20)]); llm.reply(dict(lines=[dict(block=0, anchor='before', text='Hi.')]), dict(lines=[dict(block=0, anchor='before', text='Hi.')]))
    assert S.write_block_script(f, '', 20)['lines'][0]['anchor'] is None


def test_budget_is_a_guide_not_a_hard_cut(llm):
    f = facts([block(0, 10)]); n = f[0]['budget_words']
    near = ' '.join(['word'] * (n + 2) ) + '.'
    llm.reply(dict(lines=[dict(block=0, text=near)]))
    d = S.write_block_script(f, '', 10)
    assert d['lines'][0]['words'] == n + 2 and d['remaining_problems'] == [] and len(llm.calls) == 1             # slightly over: kept, no retry
    far = ' '.join(['word'] * (n * 3)) + '.'
    llm.reply(dict(lines=[dict(block=0, text=far)]), dict(lines=[dict(block=0, text=far)]))
    d = S.write_block_script(f, '', 10)
    assert d['lines'][0]['words'] == n * 3 and d['remaining_problems'][0]['block'] == 0 and 'budget' in d['remaining_problems'][0]['problem']       # still long after the retry: kept and reported


def test_unknown_blocks_empty_text_and_invalid_json(llm):
    f = facts([block(0, 20)])
    llm.reply(dict(lines=[dict(block=7, text='x'), dict(block='a', text='y'), dict(block=0, text='  ')]), dict(lines=[dict(block=0, text='Ok.')]))
    d = S.write_block_script(f, '', 20)
    assert [l['text'] for l in d['lines']] == ['Ok.']
    assert S.check_blocks(dict(lines=[dict(block=7, text='x'), dict(block='a', text='y')]), f) == [(7, 'no such block'), (-1, "line with a bad block number 'a'")]
    llm.reply({}, {}); d = S.write_block_script(f, '', 20)
    assert d['lines'] == [] and d['remaining_problems'][0]['problem'] == 'not valid JSON' and d['llm_debug'] is not None


# ---- segment facts and script (implementation plan V1) ----

def segment(i, target, wearer_says=False, clip=None):
    return dict(id=f'S{i:02d}', index=i, start_s=0.0, dur_s=target, clip=clip or f'C{i:02d}', in_s=10.0,
                start_utc='2026-02-19T10:00:00Z', features={'speech': wearer_says})


def test_segment_facts_subtract_the_dialogue_from_the_budget():
    s = segment(0, 20, wearer_says=True)
    c = dict(clip='C00', start_utc='2026-02-19T10:00:00Z', start_s=0, end_s=60, features={'speech': True})
    f = S.segment_facts(s, c, None, None, {'clips': {'C00': 'note'}})
    assert f['clip_note'] == 'note'
    assert f['wearer_says'] == []

def test_build_messages():
    f = [dict(index=0, seconds=20, clip='C00', wearer_says=['hello'])]
    m = S.build_messages('folder note', f, 20)
    assert 'folder note' in m[1]['content']
    assert 'hello' in m[1]['content']

def test_check_segments():
    f = [dict(index=0, seconds=20, clip='C00', wearer_says=['hello'])]
    assert S.check(dict(lines=[dict(seg=0, text='x')]), f) == [(0, '1 words but the budget is 0 (the runner speaks here)')]
    assert S.check(dict(lines=[dict(seg=1, text='x')]), f) == [(1, 'no such segment')]

def test_write_script(llm):
    f = [dict(index=0, seconds=20, clip='C00', film_start_s=0.0)]
    llm.reply(dict(lines=[dict(seg=0, text='Ok.')]))
    d = S.write_script(f, '', 20)
    assert d['lines'][0]['text'] == 'Ok.'

def test_write_script_retry(llm):
    f = [dict(index=0, seconds=10, clip='C00', film_start_s=0.0)]
    # first reply is too long
    n = S.budget_words(10.0)
    far = ' '.join(['word'] * (n * 3)) + '.'
    llm.reply(dict(lines=[dict(seg=0, text=far)]), dict(lines=[dict(seg=0, text='Ok.')]))
    d = S.write_script(f, '', 10)
    assert d['lines'][0]['text'] == 'Ok.'

def test_write_script_cuts_if_still_too_long(llm):
    f = [dict(index=0, seconds=10, clip='C00', film_start_s=0.0)]
    # both replies are too long
    n = S.budget_words(10.0)
    far = ' '.join(['word'] * (n * 3)) + '.'
    llm.reply(dict(lines=[dict(seg=0, text=far)]), dict(lines=[dict(seg=0, text=far)]))
    d = S.write_script(f, '', 10)
    # The script should cut it to fit the budget.
    assert d['lines'][0]['words'] <= n

def test_words_in_window(tmp_path):
    cdir = str(tmp_path)
    import os
    os.makedirs(os.path.join(cdir, 'C00'))

    # Missing transcript
    assert S.words_in_window(cdir, 'C00', 0, 10) == []

    # Empty transcript
    with open(os.path.join(cdir, 'C00', 'transcript.json'), 'w') as f:
        import json
        json.dump({'segments': []}, f)
    assert S.words_in_window(cdir, 'C00', 0, 10) == []

    # Transcript without words, full phrase returned
    with open(os.path.join(cdir, 'C00', 'transcript.json'), 'w') as f:
        json.dump({'segments': [{'t0': 2.0, 't1': 5.0, 'text': 'hi there', 'flags': []}]}, f)
    assert S.words_in_window(cdir, 'C00', 0, 10) == ['hi there']

    # Transcript with words, partial phrase returned
    with open(os.path.join(cdir, 'C00', 'transcript.json'), 'w') as f:
        json.dump({'segments': [{'t0': 2.0, 't1': 6.0, 'text': 'a b c d', 'words': [{'w': 'a', 't0': 2, 't1': 3}, {'w': 'b', 't0': 3, 't1': 4}, {'w': 'c', 't0': 4, 't1': 5}, {'w': 'd', 't0': 5, 't1': 6}], 'flags': []}]}, f)
    # alignment missing
    # words t0+0.15, t1+0.15:
    # a: 2.15, 3.15 -> 2.65
    # b: 3.15, 4.15 -> 3.65
    # window 0 to 3.0: catches 'a'
    assert S.words_in_window(cdir, 'C00', 0, 3.0) == ['a …']
    # window 3.0 to 10: catches 'b', 'c', 'd'
    assert S.words_in_window(cdir, 'C00', 3.0, 10) == ['… b c d']

    # foreign text
    with open(os.path.join(cdir, 'C00', 'transcript.json'), 'w') as f:
        json.dump({'segments': [{'t0': 2.0, 't1': 6.0, 'text': 'un deux trois quatre', 'text_en': 'one two three four', 'lang': 'fr', 'words': [{'w': 'un', 't0': 2, 't1': 3}, {'w': 'deux', 't0': 3, 't1': 4}, {'w': 'trois', 't0': 4, 't1': 5}, {'w': 'quatre', 't0': 5, 't1': 6}], 'flags': []}]}, f)
    # catches 'un' (index 0). n=4, lo=0, hi=1. text_en[0:1] -> 'one'
    assert S.words_in_window(cdir, 'C00', 0, 3.0) == ['one …']

    # With alignment
    with open(os.path.join(cdir, 'C00', 'alignment.json'), 'w') as f:
        json.dump({'segments': [{'index': 0, 'words': [{'a0': 2, 'a1': 3, 'ok': True}]}]}, f)
    assert S.words_in_window(cdir, 'C00', 0, 3.0) == ['one …']

def test_parse_json():
    assert S._parse_json('hello {"a": 1} world') == {'a': 1}
    assert S._parse_json('hello {"a": 1,]') is None

def test_segment_facts_reads_places_and_scenes(tmp_path):
    cdir = str(tmp_path)
    import os
    os.makedirs(os.path.join(cdir, 'C00'))

    with open(os.path.join(cdir, 'C00', 'places.json'), 'w') as f:
        import json
        json.dump({'covered': True, 'summary': {'text': 'Paris', 'road': 'Rue'}, 'points': [{'nearby': [{'name': 'Tower'}]}]}, f)

    with open(os.path.join(cdir, 'C00', 'scenes.json'), 'w') as f:
        json.dump({'items': [{'ok': True, 'view': 'front', 't_s': 2, 'setting': 'city', 'description': 'busy', 'tags': ['tag1'], 'weather': 'sun'}]}, f)

    s = segment(0, 20, wearer_says=False)
    c = dict(clip='C00', start_utc='2026-02-19T10:00:00Z', start_s=0, end_s=60, features={'speech': False})
    f = S.segment_facts(s, c, cdir, None, {})
    assert 'Paris, on Rue' in f['place']
    assert 'Tower' in f['place']
    assert 'city: busy' in f['sees']
    assert 'tag1' in f['tags']
    assert 'sun' in f['weather']
