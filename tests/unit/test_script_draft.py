"""The whole-race script writer: length and pace, the request, the checks and retries (with a scripted LLM), and the drafts kept in the project."""
import json
import pytest
from strata360.edit import script_draft as SD, script_pack as SP, script_pins as PN


def L(i, t0, t1, text): return dict(id=i, t0=t0, t1=t1, text=text, words=len(text.split()), lang='en', mark=None, si=int(i.split('.')[1]), w0=0, w1=len(text.split()))


def clip(label, dur, usable, lines=()):
    return dict(label=label, clip='C' + label, duration_s=dur, usable_s=usable, usable=[(0, usable)], scene={}, note='', km=10.0, track='km 10', lines=list(lines), speech_s=sum(l['t1'] - l['t0'] for l in lines), speech_words=sum(l['words'] for l in lines))


PACK = dict(race=dict(note='n', details='d', track='t', speech_wpm=200, km_total=None), clips=[
    clip('0001', 30, 30, [L('0001.00', 2, 6, 'one two three four five six seven eight'), L('0001.01', 8, 10, 'nine ten eleven')]),
    clip('0002', 20, 20),
    clip('0003', 40, 40, [L('0003.00', 1, 5, 'twelve thirteen fourteen fifteen')])])


class Chat:
    """A scripted LLM: each call returns the next reply (a dict is turned into JSON)."""
    def __init__(self, *replies): self.replies = list(replies); self.calls = []
    def __call__(self, msgs, model, max_tokens, temperature, timeout=None, provider=None, thinking=None):
        self.calls.append(msgs); r = self.replies.pop(0); return dict(text=r if isinstance(r, str) else json.dumps(r), seconds=1.5, tokens=dict(input=100, output=50))


def clipitem(c, a, b): return dict(type='clip', clip=c, **{'from': a, 'to': b})
def vo(c, text): return dict(type='vo', clip=c, text=text, basis=[])
def broll(c, s): return dict(type='broll', clip=c, seconds=s)


GOOD = dict(title='T', story='S', items=[clipitem('0001', '0001.00', '0001.01'), broll('0002', 5), vo('0003', 'a ' * 20), clipitem('0003', '0003.00', '0003.00')], skipped=[])


def test_the_length_guide_prefers_a_target_then_the_music_then_the_footage():
    assert SD.length_guide(PACK, 200, 90) == (90.0, 'target') and SD.length_guide(PACK, 200) == (200.0, 'music')
    sec, src = SD.length_guide(PACK); assert src == 'automatic' and 60 <= sec <= 90                                       # 90 s of footage: about half of it, with a little more for the speech
    big = dict(race={}, clips=[clip('%04d' % i, 100, 100, [L('%04d.00' % i, 0, 40, 'x ' * 150)]) for i in range(20)])      # 2000 s of footage, 800 s of speech
    sec, _ = SD.length_guide(big); assert 300 < sec <= 1000 and SD.length_guide(big)[0] <= max(0.5 * 2000, 600)


def test_the_narration_pace_is_between_the_voice_and_the_runner_but_not_beyond_what_the_voice_can_do():
    assert SD.narration_wpm(PACK) == 172 and SD.narration_wpm(dict(race=dict(speech_wpm=300))) == round(145 * 1.25) and SD.narration_wpm(dict(race={})) == 145


def test_the_request_has_the_target_pace_pins_and_the_current_draft():
    pins = dict(include=['0001.00'], vo=[dict(id='v1', text='keep me', mode='anywhere')]); msgs, text = SD.build_messages(PACK, 100, 150, pins, dict(title='T', story='S', items=[vo('0001', 'old')], skipped=[]))
    u = msgs[1]['content']; assert msgs[0]['role'] == 'system' and 'TARGET FILM LENGTH: 100 seconds' in u and '<<< MUST INCLUDE' in u and '[v1]' in u and 'CURRENT DRAFT' in u and '"old"' in u and u.rstrip().endswith('by your own arithmetic; "total_s" is the final total.')
    assert 'CURRENT DRAFT' not in SD.build_messages(PACK, 100, 150)[0][1]['content'] and '=== CLIP 0002' in text


def test_a_valid_script_is_accepted_at_once_and_resolved_for_the_gui():
    chat = Chat(GOOD); d = SD.write(PACK, 25.6, 150, chat=chat, log=lambda m: None)
    assert len(chat.calls) == 1 and d['problems'] == [] and d['report']['clips_used'] == 3 and d['title'] == 'T' and d['revised'] is False
    it = d['items']; assert it[0]['refs'] == [dict(clip='C0001', si=0, w0=0, w1=8), dict(clip='C0001', si=1, w0=0, w1=3)] and it[0]['lines'] == ['0001.00', '0001.01'] and it[0]['text'].startswith('one two') and abs(it[0]['seconds'] - (10 - 2 + 0.18)) < 0.06 and it[2]['seconds'] > 0
    assert abs(d['report']['total_s'] - 25.6) < 0.2


def test_structure_problems_are_sent_back_and_the_corrected_script_is_used():
    bad = dict(items=[broll('0002', 5), clipitem('0001', '0001.00', '0001.01')], skipped=[])                                 # out of shooting order and clip 0003 neither used nor skipped
    chat = Chat(bad, GOOD); d = SD.write(PACK, 25.6, 150, chat=chat, retries=2, log=lambda m: None)
    assert len(chat.calls) == 2 and d['problems'] == [] and [r['attempt'] for r in d['runs']] == [0, 1] and len(d['runs'][0]['problems']) >= 2
    fb = chat.calls[1][-1]['content']; assert 'out of shooting order' in fb and 'neither used nor listed under skipped' in fb and chat.calls[1][-2]['role'] == 'assistant'


def test_the_writer_gives_up_after_the_retries_and_keeps_the_problems_visible():
    chat = Chat('not json', dict(items=[]), dict(items=[])); d = SD.write(PACK, 25.6, 150, chat=chat, retries=2, log=lambda m: None)
    assert len(chat.calls) == 3 and d['problems'] and d['items'] == []


def test_a_wrong_length_is_caught_by_the_real_durations():
    short = dict(items=[clipitem('0001', '0001.00', '0001.00'), broll('0002', 3), broll('0003', 3)], skipped=[]); rep, probs = SD.check(short, PACK, 100, 150)
    assert any('the target is 100 s' in p and 'add about' in p for p in probs) and rep['total_s'] < 20


def test_pins_are_enforced_and_the_user_marks_travel_with_the_pack():
    pack = json.loads(json.dumps(PACK)); pack['clips'][0]['lines'][1]['mark'] = 'never'
    draft = dict(items=[clipitem('0001', '0001.00', '0001.01'), broll('0002', 5), vo('0003', 'a ' * 20)], skipped=[])
    fixed = dict(items=[clipitem('0001', '0001.00', '0001.00'), broll('0002', 5), vo('0003', 'a ' * 20), vo('0003', 'keep me exactly')], skipped=[])
    chat = Chat(draft, fixed); d = SD.write(pack, 17.0, 150, pins=dict(vo=[dict(id='v1', text='keep me exactly', mode='clip', clip='0003')]), chat=chat, retries=1, log=lambda m: None)
    first = ' '.join(d['runs'][0]['problems']); assert 'DO NOT USE line 0001.01' in first and '[v1] is missing' in first and d['runs'][1]['problems'] == [] or 'the film is' in ' '.join(d['runs'][1]['problems'])


def test_used_lines_are_what_the_clip_items_cover():
    assert SD.used_line_ids(GOOD, PACK) == {'0001.00', '0001.01', '0003.00'}


def test_drafts_are_kept_three_at_a_time_and_pins_are_saved(project):
    f = project.folder; assert SD.load_draft(f) is None and SD.list_drafts(f) == [] and SD.load_pins(f) == {}
    names = [SD.save_draft(f, dict(n=i)) for i in range(5)]; assert len(set(names)) == 5 and SD.list_drafts(f) == sorted(names)[-3:] and SD.load_draft(f)['n'] == 4 and SD.load_draft(f, names[-2])['n'] == 3
    saved = SD.save_pins(f, dict(include=['0001.00'], junk='x')); assert saved == dict(include=['0001.00'], exclude=[], vo=[], vo_never=[]) and SD.load_pins(f) == saved


# ---- the director: gaps, the music and anchors

def gapclip(label='G01', secs=10.0):
    return dict(label=label, clip=label, duration_s=secs, usable_s=45.0, usable=[(0, 45.0)], synthetic=True, race_s=3600.0, speedup=360.0, scene={}, note='', lines=[], speech_s=0.0, speech_words=0,
                options=[dict(kind='map', default_seconds=secs), dict(kind='flyover', default_seconds=secs, note='x')], planned=None)


DPACK = dict(race=PACK['race'], clips=[PACK['clips'][0], gapclip(), PACK['clips'][1], PACK['clips'][2]],
             music=dict(length_s=245.0, bpm=97.0, bar_s=2.47, sections=[dict(t0=0.0, t1=245.0, energy=0.5)], lyrics=dict(language='en', vocal_spans=[[30.0, 60.0]], phrases=[])))


def gap(label, kind='map', seconds=12, **kw): return dict(type='gap', clip=label, kind=kind, seconds=seconds, why='w', **kw)


def test_a_gap_item_counts_in_the_film_and_is_never_asked_to_be_used():
    items = [clipitem('0001', '0001.00', '0001.01'), gap('G01', 'flyover', 12), broll('0002', 6), clipitem('0003', '0003.00', '0003.00')]
    rep, probs = SD.check(dict(items=items, skipped=[]), DPACK, 40, 150); assert rep['gap_s'] == 12.4 and not [p for p in probs if 'G01' in p or 'gap' in p]                            # 12 s at 97 bpm is 20 beats: 12.4 s
    rep, probs = SD.check(dict(items=[i for i in items if i['type'] != 'gap'], skipped=[]), DPACK, 40, 150); assert not [p for p in probs if 'G01' in p]                    # leaving the gap out is allowed


def test_gap_items_that_are_not_valid_are_sent_back_with_the_reason():
    base = [clipitem('0001', '0001.00', '0001.01')]; tail = [broll('0002', 6), clipitem('0003', '0003.00', '0003.00')]
    bad = lambda *its: SD.check(dict(items=base + list(its) + tail, skipped=[]), DPACK, 40, 150)[1]
    assert not any('kind' in p for p in bad(gap('G01', '3d'))) and any('plays for 2 to 45 seconds, not 90' in p for p in bad(gap('G01', 'map', 90)))
    assert any('0002 is a camera clip, not a gap' in p for p in bad(gap('0002'))) and any('is a gap with no words: use a gap item' in p for p in bad(clipitem('G01', '0001.00', '0001.01')))
    assert any('an anchor is' in p for p in bad(gap('G01', 'map', 12, anchor='at the chorus'))) and not any('anchor' in p for p in bad(gap('G01', 'map', 12, anchor=dict(film_s=16, why='x'))))


def test_the_length_guide_ignores_gap_clips_and_resolve_gives_gap_items_their_seconds():
    assert SD.length_guide(DPACK)[0] == SD.length_guide(PACK)[0]
    s = dict(items=[gap('G01', 'map', 12.04), dict(type='vo', clip='G01', text='a ' * 8)], skipped=[]); SD.resolve(s, DPACK, 150); assert s['items'][0]['seconds'] == 12.0 and s['items'][1]['seconds'] == 10.0         # narration over a gap plays for the whole gap clip


def test_notes_say_when_an_anchor_cannot_be_met_but_say_nothing_about_narration_over_singing():
    s = dict(items=[broll('0002', 20), dict(type='vo', clip='0003', text='a ' * 40, anchor=dict(film_s=100, why='the hook')), broll('0002', 5)], skipped=[]); SD.resolve(s, DPACK, 150)       # the narration runs 20 s to 41 s, inside the singing
    notes = [n for n in SD.director_notes(s, DPACK) if 'gap' not in n]; assert len(notes) == 1 and 'item 2' in notes[0] and 'anchored at 100 s' in notes[0] and 'starts it at 20 s' in notes[0] and 'singing' not in notes[0]


def test_the_request_carries_the_music_and_the_gap_choices_and_the_prompt_explains_gap_items_and_anchors():
    msgs, text = SD.build_messages(DPACK, 245, 150); sys_, user = msgs[0]['content'], msgs[1]['content']
    assert 'THE MUSIC (times are FILM seconds' in user and 'Sung (en): 30-60 s' in user and '=== CLIP G01' in user and 'NO FOOTAGE: a gap of 1.0 h' in user and '"type": "gap"' in user and '"anchor"' in user
    assert '"gap": a generated clip' in sys_ and 'do NOT choose how it is drawn' in sys_ and '"kind": "map"' not in sys_ and 'must approve' not in sys_ and 'THE MUSIC.' in sys_ and 'anchor' in sys_ and 'often unavoidable' in sys_ and SD.PROMPT_VERSION == 13 and 'paraphrase freely' in sys_


def test_with_the_tempo_known_every_item_counts_in_whole_beats_so_the_writers_total_matches_the_plan():
    assert SD.on_beats(3.1, 'vo', 0.5) == 3.5 and SD.on_beats(3.1, 'clip', 0.5) == 3.5 and SD.on_beats(3.1, 'broll', 0.5) == 3.0 and SD.on_beats(3.3, 'broll', 0.5) == 3.5 and SD.on_beats(0.1, 'vo', 0.5) == 0.5 and SD.on_beats(3.1, 'vo', None) == 3.1
    s = dict(items=[clipitem('0001', '0001.00', '0001.01'), broll('0002', 5), vo('0003', 'a ' * 20), clipitem('0003', '0003.00', '0003.00')], skipped=[])
    bare, _ = SD.check(s, PACK, 60, 150); beat = 60.0 / 97.0; timed, _ = SD.check(s, dict(PACK, music=dict(bpm=97.0)), 60, 150)
    assert timed['total_s'] > bare['total_s'] and timed['total_s'] - bare['total_s'] < 4 * beat + 0.2


def test_an_unreadable_last_attempt_keeps_the_best_earlier_one_and_says_so():
    long = dict(GOOD, items=GOOD['items'] + [broll('0002', 5), broll('0002', 5)]); logs = []
    chat = Chat(long, long, 'Sorry, here is some text but no JSON'); d = SD.write(PACK, 25.6, 150, chat=chat, retries=2, log=logs.append)
    assert d['items'] and d['title'] == 'T' and any('could not be read' in l for l in logs) and d['runs'][2]['problems'] == ['not valid JSON'] and d['runs'][2]['raw_head'].startswith('Sorry')
    assert d['problems'] and all('JSON' not in p for p in d['problems'])                                                             # the kept draft shows ITS problems, not the failed attempt's


def test_a_length_problem_sends_back_the_real_length_of_every_item():
    long = dict(GOOD, items=GOOD['items'] + [broll('0002', 9)]); chat = Chat(long, GOOD); SD.write(PACK, 25.6, 150, chat=chat, retries=1, log=lambda m: None)
    msg = chat.calls[1][-1]['content']; assert 'the film is' in msg and 'The real length of each of your items' in msg and '  1. clip 0001:' in msg and '  5. broll 0002: 9.0 s' in msg and 'no commentary' in msg


def test_an_anchor_far_from_where_the_items_really_land_is_sent_back_with_the_real_start():
    items = [broll('0002', 6), dict(clipitem('0003', '0003.00', '0003.00'), anchor=dict(film_s=60, why='the hook'))]
    _, probs = SD.check(dict(items=items, skipped=[]), dict(PACK, music=dict(bpm=120.0)), 12, 150); p = [x for x in probs if 'anchored at 60 s' in x]
    assert len(p) == 1 and 'item 2' in p[0] and 'it starts at 6 s' in p[0] and 'put the anchor where the items really land' in p[0]
    near = [broll('0002', 6), dict(clipitem('0003', '0003.00', '0003.00'), anchor=dict(film_s=11, why='x'))]
    assert not [x for x in SD.check(dict(items=near, skipped=[]), dict(PACK, music=dict(bpm=120.0)), 12, 150)[1] if 'anchored' in x]                  # within 8 s: the editor stretches b-roll


def test_the_narration_is_counted_at_the_voices_measured_speed_when_it_is_known():
    assert SD.narration_wpm(PACK, measured=170) == 170.0 and SD.narration_wpm(PACK) != 170.0


def test_a_view_is_only_for_clip_and_broll_items_of_a_clip_that_has_it():
    vp = dict(PACK, clips=[dict(PACK['clips'][0], you_views=dict(mid=0.8, close=0.9, far=0.1)), PACK['clips'][1], PACK['clips'][2]])
    one = lambda **kw: SD.check(dict(items=[dict(clipitem('0001', '0001.00', '0001.01'), **kw), broll('0002', 6), clipitem('0003', '0003.00', '0003.00')], skipped=[]), vp, 30, 150)[1]
    assert not [p for p in one(view='close') if 'view' in p] and any('has no far view of you (it has mid 80%, close 90%, far 10%' in p for p in one(view='far')) and any('view must be mid, close or far, not wide' in p for p in one(view='wide'))
    assert any('only clip and broll items take a "view"' in p for p in SD.check(dict(items=[vo('0001', 'a b c', ) | dict(view='close')], skipped=[]), vp, 30, 150)[1])
    assert any("0002 has no close view" in p.replace('clip ', '') for p in SD.check(dict(items=[dict(broll('0002', 6), view='close')], skipped=[]), vp, 30, 150)[1])


def test_the_prompt_explains_the_views_of_you():
    sys_ = SD.build_messages(PACK, 30, 150)[0][0]['content']; assert '"view": "mid"' in sys_ and '"close" (a face zoom' in sys_ and '"far" (ultra wide' in sys_ and SD.PROMPT_VERSION == 13


def test_a_reply_with_raw_newlines_inside_strings_is_still_read():
    raw = '{"title": "T", "story": "two\nlines", "items": [], "skipped": []}'
    assert SD.parse(raw)['story'] == 'two\nlines' and SD.parse('```json\n' + raw + '\n```')['title'] == 'T' and SD.parse('no json here') is None


def test_gaps_of_an_hour_or_more_that_the_script_leaves_unfilled_are_noted_and_the_prompt_asks_for_most_to_be_filled():
    s = dict(items=[broll('0002', 6)], skipped=[]); SD.resolve(s, DPACK, 150)
    assert any('1 gap(s) of an hour or more are not filled: G01' in n for n in SD.director_notes(s, DPACK))
    s2 = dict(items=[broll('0002', 6), gap('G01')], skipped=[]); SD.resolve(s2, DPACK, 150); assert not any('not filled' in n for n in SD.director_notes(s2, DPACK))
    short = dict(DPACK, clips=[dict(c, race_s=1800.0) if c.get('synthetic') else c for c in DPACK['clips']]); assert not any('not filled' in n for n in SD.director_notes(s, short))                    # a half hour gap is not asked for
    assert 'fill MOST gaps of an hour or more' in SD.build_messages(DPACK, 245, 150)[0][0]['content']


def test_a_drafts_basis_is_always_a_list_of_strings():
    d = SD.tidy(dict(items=[dict(type='vo', basis='one string'), dict(type='vo', basis=None), dict(type='vo', basis=['a', 2]), dict(type='broll')]))
    assert [it.get('basis') for it in d['items']] == [['one string'], [], ['a', '2'], None]
    assert SD.parse('{"items": [{"type": "vo", "basis": "x"}]}')['items'][0]['basis'] == ['x']


def test_the_writer_is_asked_whether_the_length_suits_and_the_answer_is_kept_when_it_makes_sense():
    sys_ = SD.build_messages(PACK, 30, 150)[0][0]['content']; assert '"length_note"' in sys_ and 'too_long' in sys_ and 'ideal_s' in sys_ and 'THE LENGTH.' in sys_ and 'roughly that moment of the film' in sys_
    assert SD.length_note(dict(length_note=dict(verdict='too_long', ideal_s='210', why=' padding in the middle '))) == dict(verdict='too_long', ideal_s=210.0, why='padding in the middle')
    assert SD.length_note(dict(length_note=dict(verdict='fits'))) == dict(verdict='fits', ideal_s=None, why='') and SD.length_note(dict(length_note=dict(verdict='huge'))) is None and SD.length_note({}) is None and SD.length_note(dict(length_note='fine')) is None
    assert SD.length_note(dict(length_note=dict(verdict='too_short', ideal_s='soon'))) == dict(verdict='too_short', ideal_s=None, why='')
