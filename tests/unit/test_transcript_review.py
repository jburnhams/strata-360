"""The worst-first review queue: speaking rate, priority, the reviewed marks and the two endpoints."""
import json, os
from projects import CLIP_ID
from strata360.analysis import transcript_edits as TE, transcript_review as TR


def seg(words, t0=1.0, step=0.5, p=0.9, **kw):
    ws = [dict(w=w, t0=t0 + i * step, t1=t0 + i * step + step * 0.8, p=p) for i, w in enumerate(words)]
    return dict(dict(t0=t0, t1=ws[-1]['t1'] if ws else t0, lang='en', text=' '.join(words), text_en=' '.join(words), avg_logprob=-0.2, no_speech=0.01, words=ws), **kw)


class TestRate:
    def test_words_a_second_over_the_span_of_the_words(self): assert TR.rate(seg(['a'] * 5, step=0.25)) == 4.17         # 5 words over 1.2 s

    def test_a_short_phrase_has_no_pace(self): assert TR.rate(seg(['hi', 'there', 'you'])) is None

    def test_empty_words_are_not_counted(self): assert TR.rate(seg(['a', ' ', 'b', 'c', 'd'], step=0.5)) == 1.67         # four words over 2.4 s

    def test_play_rate_slows_only_fast_speech_and_never_below_the_floor(self):
        assert TR.play_rate(None) == 1.0 and TR.play_rate(2.5) == 1.0 and TR.play_rate(3.5) == 1.0
        assert TR.play_rate(7.0) == 0.5 and TR.play_rate(5.25) == 0.67 and TR.play_rate(10.0) == 0.5


class TestPriority:
    def test_unsure_fast_and_flagged_phrases_rank_above_a_calm_sure_one(self):
        calm = TR.stats(seg(['we', 'are', 'fine', 'here'], step=0.5))
        fast = TR.stats(seg(['we', 'are', 'fine', 'here'], step=0.1))
        unsure = TR.stats(dict(seg(['we', 'are', 'fine', 'here'], step=0.5, p=0.3), avg_logprob=-0.9))
        flagged = TR.stats(dict(seg(['we', 'are', 'fine', 'here'], step=0.5), flags=['hallucination_phrase']))
        assert calm['priority'] < fast['priority'] and calm['priority'] < unsure['priority'] and calm['priority'] < flagged['priority']
        assert unsure['low_words'] == 4 and flagged['flags'] == ['hallucination_phrase']

    def test_a_phrase_without_a_logprob_or_pace_still_has_a_priority(self):
        s = seg(['hi']); del s['avg_logprob']; assert TR.stats(s)['priority'] == 0.0


class TestReviewedMarks:
    def test_marking_and_unmarking(self, tmp_path):
        d = str(tmp_path); assert TR.load(d) == {}
        TR.set_reviewed(d, 2, 3.2); assert TR.is_reviewed(TR.load(d), 2, 3.2) and not TR.is_reviewed(TR.load(d), 1, 3.2)
        TR.set_reviewed(d, 2, 3.2, False); assert TR.load(d) == {}

    def test_a_mark_is_stale_when_the_phrase_moved(self, tmp_path):
        d = str(tmp_path); TR.set_reviewed(d, 0, 1.0); assert not TR.is_reviewed(TR.load(d), 0, 2.0)

    def test_a_damaged_file_is_ignored(self, tmp_path):
        (tmp_path / TR.FILE).write_text('{nope'); assert TR.load(str(tmp_path)) == {}


class TestQueue:
    def make(self, tmp_path, segments):
        d = str(tmp_path); json.dump(dict(segments=segments), open(os.path.join(d, 'transcript.json'), 'w')); return d

    def test_worst_first_reviewed_last_and_corrections_shown(self, tmp_path):
        d = self.make(tmp_path, [seg(['calm', 'words', 'here'], t0=1.0), seg(['fast'] * 6, t0=10.0, step=0.12), dict(t0=30.0, t1=31.0, lang='en', text='', words=[]), seg(['bad', 'one'], t0=20.0, p=0.2, avg_logprob=-1.2)])
        TE.set_user(d, 0, 0, 'tranquil'); TR.set_reviewed(d, 0, 1.0)
        items = TR.queue([d], TE.load_effective, lambda _: 'C1')
        assert [(x['si'], x['reviewed']) for x in items] == [(3, False), (1, False), (0, True)]                       # the empty phrase is left out
        assert items[2]['words'][0]['w'] == 'tranquil' and items[2]['words'][0]['e']['orig'] == 'calm' and items[1]['play_rate'] < 1.0 and items[0]['play_rate'] == 1.0
        assert items[1]['play0'] == 9.7 and items[1]['clip'] == 'C1'

    def test_a_clip_without_a_transcript_is_skipped(self, tmp_path): assert TR.queue([str(tmp_path)], TE.load_effective, lambda _: 'C1') == []


class TestEndpoints:
    TRANSCRIPT = dict(segments=[seg(['we', 'are', 'fine'], t0=1.0), seg(['so', 'fast', 'it', 'is', 'blurred', 'out'], t0=5.0, step=0.12, p=0.3)])

    def test_the_queue_lists_the_worst_phrase_first(self, client, project):
        project.add_clip(transcript=self.TRANSCRIPT); r = client.get('/api/transcript/review', params=dict(folder=project.folder)).json()
        assert [x['si'] for x in r['items']] == [1, 0] and r['todo'] == 2 and r['total'] == 2 and r['items'][0]['clip'] == CLIP_ID and r['fast_wps'] == TR.FAST_WPS

    def test_reviewing_a_phrase_moves_it_to_the_end_and_can_be_undone(self, client, project):
        project.add_clip(transcript=self.TRANSCRIPT); q = dict(folder=project.folder, clip=CLIP_ID, seg=1)
        assert client.post('/api/transcript/reviewed', json=q).status_code == 200
        r = client.get('/api/transcript/review', params=dict(folder=project.folder)).json(); assert [x['si'] for x in r['items']] == [0, 1] and r['todo'] == 1
        client.post('/api/transcript/reviewed', json=dict(q, state=False)); assert client.get('/api/transcript/review', params=dict(folder=project.folder)).json()['todo'] == 2

    def test_an_unknown_phrase_is_refused(self, client, project):
        project.add_clip(transcript=self.TRANSCRIPT); assert client.post('/api/transcript/reviewed', json=dict(folder=project.folder, clip=CLIP_ID, seg=9)).status_code == 404
        assert client.post('/api/transcript/reviewed', json=dict(folder=project.folder, clip=CLIP_ID, seg='x')).status_code == 404
