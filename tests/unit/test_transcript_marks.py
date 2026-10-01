"""The user's MUST USE / NEVER USE marks on transcript words, and what they do to the writer's lines and pins."""
import json, os
import pytest
from strata360.analysis import transcript_marks as TM
from strata360.edit import script_pack as SP, script_pins as PN
from projects import CLIP_ID


def words(*ws, t=0.0): return [dict(w=w, t0=round(t + 0.5 * i, 2), t1=round(t + 0.5 * i + 0.4, 2), p=0.9) for i, w in enumerate(ws)]


TR = dict(segments=[dict(t0=1.0, t1=5.0, text='so we are doing fine today really', text_en='so we are doing fine today really', lang='en', words=words('so', 'we', 'are', 'doing', 'fine', 'today', 'really', t=1.0)),
                    dict(t0=8.0, t1=9.5, text='it is wet', text_en='it is wet', lang='en', words=words('it', 'is', 'wet', t=8.0))])


@pytest.fixture
def clipdir(project):
    return project.add_clip(transcript=TR)


def test_marks_are_stored_by_word_and_cleared(clipdir):
    TM.set_spans(clipdir, [(0, 2, 4)], 'never'); assert TM.states(clipdir) == {(0, 2): 'never', (0, 3): 'never', (0, 4): 'never'}
    TM.set_spans(clipdir, [(0, 4, 4), (1, 0, 0)], 'must'); assert TM.states(clipdir)[(0, 4)] == 'must' and TM.states(clipdir)[(1, 0)] == 'must'
    TM.set_spans(clipdir, [(0, 0, 6)], None); assert TM.states(clipdir) == {(1, 0): 'must'}                                    # None clears; other segments untouched
    TM.set_spans(clipdir, [(0, 3, 2)], 'must'); assert (0, 2) in TM.states(clipdir) and (0, 3) in TM.states(clipdir)           # a backwards span is fine


def test_bad_words_and_states_are_refused(clipdir):
    with pytest.raises(IndexError): TM.set_spans(clipdir, [(0, 0, 99)], 'must')
    with pytest.raises(IndexError): TM.set_spans(clipdir, [(5, 0, 0)], 'must')
    with pytest.raises(ValueError): TM.set_spans(clipdir, [(0, 0, 0)], 'maybe')


def test_a_mark_goes_stale_when_the_recognised_word_changes(clipdir):
    TM.set_spans(clipdir, [(0, 1, 1)], 'must'); assert TM.states(clipdir) == {(0, 1): 'must'}
    tr = json.loads(json.dumps(TR)); tr['segments'][0]['words'][1]['w'] = 'WE'; json.dump(tr, open(os.path.join(clipdir, 'transcript.json'), 'w'))
    assert TM.states(clipdir) == {}


def test_annotate_puts_the_state_on_the_words(clipdir):
    TM.set_spans(clipdir, [(1, 1, 2)], 'never'); a = TM.annotate(TR, clipdir)
    assert [w.get('mark') for w in a['segments'][1]['words']] == [None, 'never', 'never'] and 'mark' not in TR['segments'][1]['words'][1]


def pack_for(clipdir):
    label = SP.label_of(CLIP_ID); lines = SP.transcript_lines(clipdir, label)
    return dict(race=dict(note='', details='', track=''), clips=[dict(label=label, clip=CLIP_ID, duration_s=20, usable_s=20, usable=[(0, 20)], scene={}, note='', lines=lines, speech_s=0, speech_words=0)]), lines


def test_lines_are_split_where_the_mark_changes_and_only_there(clipdir):
    _, plain = pack_for(clipdir); assert [l['id'] for l in plain] == ['0019.00', '0019.01'] and all(l['mark'] is None for l in plain)
    TM.set_spans(clipdir, [(0, 2, 3)], 'never'); TM.set_spans(clipdir, [(0, 6, 6)], 'must'); _, lines = pack_for(clipdir)
    assert [(l['id'], l['text'], l['mark']) for l in lines] == [('0019.00.1', 'so we', None), ('0019.00.2', 'are doing', 'never'), ('0019.00.3', 'fine today', None), ('0019.00.4', 'really', 'must'), ('0019.01', 'it is wet', None)]
    assert lines[1]['t0'] < lines[1]['t1'] and lines[0]['t1'] <= lines[2]['t0'] + 0.01 and abs(lines[1]['t0'] - 2.15) < 0.01          # times of the words inside the piece (+ the recogniser's 0.15 s lag)


def test_pins_see_marks_as_include_and_exclude_and_base_ids_stand_for_their_pieces(clipdir):
    TM.set_spans(clipdir, [(0, 2, 3)], 'never'); TM.set_spans(clipdir, [(1, 0, 2)], 'must'); pack, _ = pack_for(clipdir)
    assert PN.marks(None, pack) == {'0019.00.2': 'never', '0019.01': 'must'}
    assert PN.expand('0019.00', pack) == ['0019.00.1', '0019.00.2', '0019.00.3'] and PN.expand('0019.00.2', pack) == ['0019.00.2'] and PN.expand('0019.00.1..0019.01', pack)[-1] == '0019.01'
    assert PN.marks(dict(exclude=['0019.01']), pack)['0019.01'] == 'never'                                                         # never wins
    txt = SP.render(pack, marks=PN.marks(None, pack)); assert '<<< DO NOT USE' in txt and '<<< MUST INCLUDE' in txt
    ok = dict(items=[dict(type='clip', clip='0019', **{'from': '0019.00.1', 'to': '0019.00.1'}), dict(type='clip', clip='0019', **{'from': '0019.01', 'to': '0019.01'})]); assert PN.check(ok, pack, None) == []
    bad = dict(items=[dict(type='clip', clip='0019', **{'from': '0019.00.1', 'to': '0019.00.3'})]); p = ' '.join(PN.check(bad, pack, None)); assert 'DO NOT USE line 0019.00.2' in p and 'MUST INCLUDE line 0019.01' in p


def test_the_narration_fields_in_the_notes_become_pins(clipdir):
    pack, _ = pack_for(clipdir)
    notes = dict(vo_must=dict(folder='First thing.\n\nSecond thing.', folder_ordered=True, clips={CLIP_ID: 'Said in this clip.\nAnd this.', 'OTHER_0001_D': 'ignored: no such clip'}))
    pins = PN.notes_pins(notes, pack); assert [(p['id'], p['mode'], p.get('clip')) for p in pins] == [('n1', 'ordered', None), ('n2', 'ordered', None), ('0019-1', 'clip', '0019'), ('0019-2', 'clip', '0019')]
    assert PN.notes_pins(dict(vo_must=dict(folder='Anywhere piece.', folder_ordered=False)), pack)[0]['mode'] == 'anywhere'
    merged = PN.project_pins(notes, pack, dict(include=['0019.01'], vo=[dict(id='v1', text='mine', mode='anywhere')])); assert merged['include'] == ['0019.01'] and [p['id'] for p in merged['vo']] == ['v1', 'n1', 'n2', '0019-1', '0019-2']


def test_never_say_phrases_are_in_the_prompt_and_checked(clipdir):
    pack, _ = pack_for(clipdir); pins = dict(vo_never=['best day ever'])
    assert 'must never say: "best day ever"' in PN.render_constraints(pins, pack, 100, 150)
    said = dict(items=[dict(type='vo', clip='0019', text='What a great day, the best day ever, truly.')]); assert any('never to say' in x for x in PN.check(said, pack, pins)) and PN.check(dict(items=[dict(type='vo', clip='0019', text='A fine day.')]), pack, pins) == []
