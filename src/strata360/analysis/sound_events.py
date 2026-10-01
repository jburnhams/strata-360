"""What the sound is, second by second: a sound-event classifier (Audio Spectrogram Transformer trained on AudioSet, 527 classes; MIT/ast-finetuned-audioset-10-10-0.4593, BSD-3-Clause, runs locally)
on the clip's stored original audio. The classes are grouped into the categories an editor cares about, and each category has a role and a suggested level in the film:

  voice     speech, shouting             full volume when it is you (the wearer), lower for others          energy   cheering, applause, laughter    lifted: it carries the mood
  bed       crowd murmur                 under everything                                                    texture  footsteps, water, nature, bells quiet, for place and rhythm
  avoid     wind, handling noise, traffic/engines, music playing nearby, beeps       pulled right down (music nearby clashes with the film's own music)

`audio_events.json`: windows [{t0, t1, cats: {category: score 0..1}, top: [[label, p]]}] (6 s windows every 3 s). `window_mix` turns the windows over a stretch of film into a suggested gain and the reasons;
editing decisions (and fades) stay with the editor."""
import json, os
import numpy as np

MODEL_DIR = os.environ.get('STRATA360_AST') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'models', 'ast')
MODEL_ID = 'MIT/ast-finetuned-audioset-10-10-0.4593'
WIN_S = 6.0; HOP_S = 3.0

CATEGORIES = {   # category -> AudioSet class names (the category score is the highest probability among them)
    'speech': ['Speech', 'Male speech, man speaking', 'Female speech, woman speaking', 'Child speech, kid speaking', 'Conversation', 'Narration, monologue'],
    'shouting': ['Shout', 'Bellow', 'Yell', 'Children shouting', 'Whoop'],
    'laughter': ['Laughter', 'Belly laugh', 'Giggle', 'Chuckle, chortle', 'Baby laughter'],
    'cheering': ['Cheering', 'Applause', 'Clapping', 'Whistling'],
    'crowd': ['Crowd', 'Hubbub, speech noise, speech babble'],
    'breathing': ['Breathing', 'Gasp', 'Pant', 'Grunt', 'Cough', 'Sneeze', 'Sniff'],
    'footsteps': ['Run', 'Walk, footsteps', 'Crunch', 'Shuffle'],
    'wind': ['Wind', 'Wind noise (microphone)'],
    'handling': ['Rustle', 'Thump, thud', 'Scrape', 'Clicking', 'Zipper (clothing)', 'Crackle', 'Noise', 'Static', 'Rub', 'Clatter', 'Slap, smack', 'Knock', 'Tap'],
    'nature': ['Bird', 'Bird vocalization, bird call, bird song', 'Bird flight, flapping wings', 'Insect', 'Animal', 'Wild animals', 'Rustling leaves', 'Frog', 'Owl', 'Crow'],
    'animals': ['Domestic animals, pets', 'Dog', 'Livestock, farm animals, working animals', 'Horse', 'Cattle, bovinae', 'Sheep', 'Cat', 'Goat', 'Pig'],
    'water': ['Water', 'Stream', 'Waterfall', 'Rain', 'Raindrop', 'Rain on surface', 'Thunderstorm', 'Thunder', 'Gurgling', 'Splash, splatter', 'Drip'],
    'vehicle': ['Vehicle', 'Car', 'Motor vehicle (road)', 'Car passing by', 'Truck', 'Motorcycle', 'Traffic noise, roadway noise', 'Engine', 'Light engine (high frequency)', 'Medium engine (mid frequency)',
                'Heavy engine (low frequency)', 'Train', 'Aircraft', 'Helicopter', 'Fixed-wing aircraft, airplane', 'Bicycle', 'Vehicle horn, car horn, honking', 'Siren', 'Emergency vehicle', 'Race car, auto racing'],
    'music': ['Music', 'Background music', 'Pop music', 'Rock music', 'Electronic music', 'Dance music', 'Folk music', 'Musical instrument', 'Singing', 'Male singing', 'Female singing', 'Drum kit', 'Drum'],
    'bells': ['Bell', 'Church bell', 'Cowbell', 'Bicycle bell', 'Tubular bells', 'Wind chime', 'Jingle bell', 'Tinkle'],
    'beeps': ['Beep, bleep', 'Alarm', 'Alarm clock', 'Smoke detector, smoke alarm', 'Telephone bell ringing', 'Buzzer', 'Reversing beeps'],
}
HINTS = {   # category -> (role, suggested level in dB relative to full volume)
    'speech': ('voice', 0.0), 'shouting': ('voice', -3.0), 'laughter': ('energy', -3.0), 'cheering': ('energy', -6.0), 'crowd': ('bed', -14.0), 'breathing': ('texture', -12.0), 'footsteps': ('texture', -12.0),
    'nature': ('texture', -10.0), 'animals': ('texture', -10.0), 'water': ('texture', -10.0), 'bells': ('texture', -9.0),
    'wind': ('avoid', -26.0), 'handling': ('avoid', -26.0), 'vehicle': ('avoid', -16.0), 'music': ('avoid', -20.0), 'beeps': ('avoid', -18.0)}
QUIET_DB = -18.0        # nothing recognisable: a quiet bed
_M = {}


def model_ready(): return os.path.exists(os.path.join(MODEL_DIR, 'model.safetensors'))


def fetch_model(log=print):
    from huggingface_hub import snapshot_download
    log('downloading the sound classifier (346 MB) ...'); snapshot_download(MODEL_ID, local_dir=MODEL_DIR, allow_patterns=['*.json', 'model.safetensors'])


def _model():
    if 'm' not in _M:
        import torch
        from transformers import ASTFeatureExtractor, ASTForAudioClassification
        torch.set_num_threads(2); _M['fe'] = ASTFeatureExtractor.from_pretrained(MODEL_DIR); _M['m'] = ASTForAudioClassification.from_pretrained(MODEL_DIR).eval()
        _M['labels'] = [_M['m'].config.id2label[i] for i in range(len(_M['m'].config.id2label))]
        idx = {l: i for i, l in enumerate(_M['labels'])}; _M['cat_idx'] = {c: [idx[n] for n in names if n in idx] for c, names in CATEGORIES.items()}
    return _M


def classify(path, win_s=WIN_S, hop_s=HOP_S, batch=8, progress=None):
    """audio_events.json body for one audio file."""
    import torch
    from strata360.audio import dsp
    M = _model(); x = dsp.ffmpeg_filter(dsp.load_audio(path, 1)[:, 0], dsp.SR, 'anull', out_sr=16000)[:, 0]; dur = len(x) / 16000.0
    starts = [0.0] if dur <= win_s else list(np.arange(0.0, max(dur - win_s, 0.0) + 1e-6, hop_s)) + ([] if abs((dur - win_s) % hop_s) < 1e-6 else [dur - win_s]); wins = []
    for b in range(0, len(starts), batch):
        chunk = starts[b:b + batch]; feats = M['fe']([x[int(s * 16000):int((s + win_s) * 16000)] for s in chunk], sampling_rate=16000, return_tensors='pt')
        with torch.no_grad(): p = torch.sigmoid(M['m'](**feats).logits).numpy()
        for s, pr in zip(chunk, p):
            cats = {c: round(float(pr[ix].max()), 3) for c, ix in M['cat_idx'].items() if len(ix)}; top = np.argsort(-pr)[:5]
            wins.append(dict(t0=round(float(s), 2), t1=round(float(min(s + win_s, dur)), 2), cats=cats, top=[[M['labels'][i], round(float(pr[i]), 3)] for i in top]))
        progress and progress(min(b + batch, len(starts)), len(starts))
    return dict(model=MODEL_ID, win_s=win_s, hop_s=hop_s, duration_s=round(dur, 2), windows=wins, categories=list(CATEGORIES))


def category_seconds(doc, thr=0.3):
    """Seconds of the clip in which each category is present (score at least `thr`), by window centre: a quick summary for the app."""
    out = {}
    for w in doc['windows']:
        for c, s in w['cats'].items():
            if s >= thr: out[c] = out.get(c, 0.0) + min(HOP_S, w['t1'] - w['t0'])
    return {c: round(v, 1) for c, v in sorted(out.items(), key=lambda kv: -kv[1])}


def scores_between(doc, t0, t1):
    """Mean category scores over [t0, t1], from the windows that overlap it (weighted by overlap)."""
    acc = {}; tot = 0.0
    for w in doc['windows']:
        o = min(t1, w['t1']) - max(t0, w['t0'])
        if o <= 0: continue
        tot += o
        for c, s in w['cats'].items(): acc[c] = acc.get(c, 0.0) + s * o
    return {c: v / tot for c, v in acc.items()} if tot > 0 else {}


def window_mix(doc, t0, t1, wearer_speaks=False, present=0.3):
    """Suggested level for the clip's own sound over [t0, t1]: dict(gain_db, why, cats). The wearer speaking is always full volume. Otherwise the level follows what is there: each category above
    `present` pulls the level towards its suggested level in proportion to its score, and a strong 'avoid' sound (wind, handling noise, traffic, music, beeps) pulls it down the same way."""
    cats = scores_between(doc, t0, t1) if doc else {}
    if wearer_speaks: return dict(gain_db=0.0, why=['you are speaking'], cats=cats)
    hot = {c: s for c, s in cats.items() if s >= present and c in HINTS and c != 'speech'}
    if not hot:
        sp = cats.get('speech', 0.0)
        return dict(gain_db=-6.0 if sp >= 0.5 else QUIET_DB, why=['other people speaking'] if sp >= 0.5 else ['nothing recognisable: a quiet bed'], cats=cats)
    wsum = sum(hot.values()); g = sum(HINTS[c][1] * s for c, s in hot.items()) / wsum
    wanted = [c for c in hot if HINTS[c][0] != 'avoid']; unwanted = [c for c in hot if HINTS[c][0] == 'avoid']
    if wanted and unwanted: g = min(g, max(HINTS[c][1] for c in wanted)) - 3.0 * max(hot[c] for c in unwanted)             # something good, but with noise on it: a little under the good level
    why = [f'{c} {hot[c]:.1f} ({HINTS[c][0]})' for c in sorted(hot, key=lambda c: -hot[c])[:3]]
    return dict(gain_db=round(float(np.clip(g, -30.0, 0.0)), 1), why=why, cats=cats)
