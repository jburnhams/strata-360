"""Experiment (music and speech): does speech recognition find the words in the music track, and where are they?

  python scripts/lyrics_spike.py TRACK.mp3 OUT.json [--model small]

Runs faster-whisper (the same engine as the speech stage) on the whole track with word times and its voice-activity filter, language detected. Prints the language, how much of the track is sung, the
phrases with their times and the confidence of each word, so the results can be judged by ear: are there words, are they right, do the sung stretches fall in the gaps between the sections?"""
import argparse, json, sys, time


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('track'); ap.add_argument('out'); ap.add_argument('--model', default='small'); ap.add_argument('--no-vad', action='store_true', help='do not pre-filter with the voice-activity detector (music can hide singing from it, and invites invented words)'); a = ap.parse_args()
    from faster_whisper import WhisperModel
    t0 = time.time(); m = WhisperModel(a.model, device='cpu', compute_type='int8')
    segs, info = m.transcribe(a.track, word_timestamps=True, vad_filter=not a.no_vad, vad_parameters=dict(min_silence_duration_ms=500), beam_size=5, condition_on_previous_text=False)
    out = []
    for s in segs:
        out.append(dict(t0=round(s.start, 2), t1=round(s.end, 2), text=s.text.strip(), no_speech=round(s.no_speech_prob, 2), avg_logprob=round(s.avg_logprob, 2),
                        words=[dict(w=w.word.strip(), t0=round(w.start, 2), t1=round(w.end, 2), p=round(w.probability, 2)) for w in (s.words or [])]))
    dur = info.duration; sung = sum(s['t1'] - s['t0'] for s in out)
    doc = dict(model=a.model, language=info.language, language_probability=round(info.language_probability, 2), duration_s=round(dur, 1), sung_s=round(sung, 1), seconds=round(time.time() - t0, 1), segments=out)
    json.dump(doc, open(a.out, 'w'), indent=1, ensure_ascii=False)
    print(f"{a.track}: {dur:.0f} s, language {info.language} ({info.language_probability:.2f}), {len(out)} phrases covering {sung:.0f} s ({100 * sung / dur:.0f}%), {doc['seconds']} s to run")
    for s in out: print(f"  {s['t0']:6.1f}-{s['t1']:6.1f}  p={s['avg_logprob']:+.2f} ns={s['no_speech']:.2f}  {s['text']}")


if __name__ == '__main__':
    main()
