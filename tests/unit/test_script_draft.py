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
