"""strata360 command line. Typical use on a new race collection:

    ./strata360 doctor                                   # check the environment
    ./strata360 init belgium-2026 --library /path/to/clips --languages en,fr,nl,de --clock-offset-hours 1
    ./strata360 run belgium-2026                         # ingest, audio, transcribe, align, exposure (cached: safe to re-run)
    ./strata360 status belgium-2026
    ./strata360 report belgium-2026
"""
import numpy as np
import argparse, csv, datetime as dt, glob, json, os, subprocess, sys, time
from strata360.pipeline import config, clips as clipmod, runner
from strata360.pipeline.stages import STAGES, ORDER


def cmd_init(a):
    rd = config.race_dir(a.name)
    if os.path.exists(os.path.join(rd, 'race.json')) and not a.force: sys.exit(f'{rd}/race.json exists (use --force to overwrite)')
    if not os.path.isdir(a.library): sys.exit(f'library folder not found: {a.library}')
    cfg = json.loads(json.dumps(config.DEFAULTS)); cfg['name'] = a.name; cfg['library'] = os.path.abspath(a.library)
    if a.languages: cfg['languages'] = a.languages.split(',')
    if a.align_languages: cfg['align_languages'] = a.align_languages.split(',')
    if a.whisper_model: cfg['whisper_model'] = a.whisper_model
    cfg['camera_clock'] = dict(utc_offset_hours=a.clock_offset_hours, verified=a.clock_verified, note=a.clock_note or '')
    config.save(a.name, cfg); cl, other = clipmod.discover(cfg['library'])
    print(f'race {a.name!r} created at {rd}\n  library {cfg["library"]}: {len(cl)} clips ({sum(c.size for c in cl) / 1e9:.1f} GB), {len(other)} other files')
    for p, r in other[:8]: print(f'    not processed: {os.path.basename(p)} ({r})')
    print(f'  languages {cfg["languages"]}, camera clock offset {a.clock_offset_hours} h ({"verified" if a.clock_verified else "NOT verified: start times will be provisional"})')
    print('next: ./strata360 run', a.name)


def cmd_catalog(a):
    cfg = config.load(a.name); cl, other = clipmod.discover(cfg['library'])
    rows = [c.to_dict() for c in cl]
    os.makedirs(config.race_dir(a.name), exist_ok=True)
    with open(os.path.join(config.race_dir(a.name), 'catalog.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ['id']); w.writeheader(); [w.writerow(r) for r in rows]
    for c in cl: print(f'{c.id}  {c.size / 1e6:8.0f} MB  lrf={"yes" if c.lrf else "no"}  filename time {c.filename_time}')
    print(f'{len(cl)} clips; {len(other)} unsupported files')


def worker_allowed(name):
    """False (with the reason printed) when starting a worker on this project now would break the limits: one is the first free, more only with plenty of free memory (pipeline/resources.py; the app checks the same)."""
    from strata360.pipeline import resources
    wk = runner.workers(name); ok, why = resources.may_start_extra_worker(len(wk), config.load(name))
    if not ok: print(f"not starting another worker: {len(wk)} already running (pid {', '.join(map(str, wk))}); {why}")
    return ok


def cmd_run(a):
    if not worker_allowed(a.name): return
    stages = a.stages.split(',') if a.stages else None
    res = runner.run(a.name, stages, a.clips, a.force, fail_fast=a.fail_fast)
    failed = [k for k, v in res.items() if v == 'failed']
    if failed: sys.exit(f'{len(failed)} stage runs failed (see `strata360 status {a.name}`)')


def _state_symbol(race, cfg, clip, name, state):
    st = STAGES[name]; s = state.get(name)
    if not s: return '-'
    if s['status'] == 'failed': return 'FAIL'
    if s['status'] == 'retry': return 'retry'
    deps = {d: state.get(d, {}).get('key') for d in st.deps}
    if name == 'ingest':                                             # its key is frozen (a clock change re-times, it does not invalidate): stale only when the clock changed since it ran
        return 'ok' if s.get('clock') == runner._sha(cfg.get('camera_clock')) and s.get('fp', clip.fingerprint) == clip.fingerprint else 'stale'
    done, _, _ = runner._cached(race, st, clip, cfg, state, runner.clip_dir(race, clip.id))
    return 'ok' if done else 'stale'


def cmd_status(a):
    cfg = config.load(a.name); cl, other = clipmod.discover(cfg['library']); names = [n for n in ORDER if n in cfg['stages'] or a.all]
    print(f'{"clip":30s} ' + ' '.join(f'{n:>10s}' for n in names)); tot = {n: 0 for n in names}; secs = 0
    for c in cl:
        state = runner.load_state(a.name, c.id); row = [_state_symbol(a.name, cfg, c, n, state) for n in names]
        for n, r in zip(names, row): tot[n] += r == 'ok'
        secs += sum(v.get('seconds', 0) for v in state.values() if isinstance(v, dict))
        print(f'{c.id:30s} ' + ' '.join(f'{r:>10s}' for r in row))
        if a.errors:
            for n in names:
                if state.get(n, {}).get('status') == 'failed': print(f'    {n}: {state[n]["error"]}')
    print(f'{"complete":30s} ' + ' '.join(f'{tot[n]:>7d}/{len(cl):<2d}' for n in names) + f'   ({secs / 60:.1f} min compute recorded)')


def cmd_show(a):
    cfg = config.load(a.name); d = runner.clip_dir(a.name, a.clip)
    if not os.path.isdir(d): sys.exit(f'no such clip directory: {d}')
    for fn in ('clip.json',):
        if os.path.exists(f'{d}/{fn}'): c = json.load(open(f'{d}/{fn}')); print(json.dumps({k: c[k] for k in ('clip_id', 'camera', 'video', 'audio', 'colour_mode', 'duration_s', 'time', 'notes')}, indent=1))
    state = runner.load_state(a.name, a.clip); print('stages:', {k: v['status'] for k, v in state.items()})


def _load(d, fn):
    p = os.path.join(d, fn); return json.load(open(p)) if os.path.exists(p) else None


def cmd_report(a):
    cfg = config.load(a.name); cl, _ = clipmod.discover(cfg['library']); R = dict(race=a.name, clips=len(cl), duration_s=0.0, dropped_frames=0, colour_modes={}, utc_status={}, first_utc=None, last_utc=None,
                                                                            audio=dict(lufs_min=None, lufs_max=None, clips_with_clipping=0, label_seconds={}), speech=dict(words_by_language={}, segments=0, suspect_segments=0, translated_segments=0),
                                                                            alignment=dict(words=0, words_ok=0, gaps=0, safe_cuts=0), exposure=dict(mean_lin_min=None, mean_lin_max=None, max_range_stops=0.0))
    lufs = []
    for c in cl:
        d = runner.clip_dir(a.name, c.id); cj = _load(d, 'clip.json')
        if cj:
            R['duration_s'] += cj['duration_s']; R['dropped_frames'] += cj['video']['dropped_frames']
            R['colour_modes'][cj['colour_mode']] = R['colour_modes'].get(cj['colour_mode'], 0) + 1; R['utc_status'][cj['time']['utc_status']] = R['utc_status'].get(cj['time']['utc_status'], 0) + 1
            s = cj['time']['start_utc']
            if s: R['first_utc'] = min(filter(None, [R['first_utc'], s])); R['last_utc'] = max(filter(None, [R['last_utc'], cj['time']['end_utc']]))
        au = _load(d, 'audio.json')
        if au:
            lufs.append(au['summary']['integrated_lufs']); R['audio']['clips_with_clipping'] += au['summary']['clipped_samples'] > 0
            for sg in au['segments']: R['audio']['label_seconds'][sg['label']] = round(R['audio']['label_seconds'].get(sg['label'], 0) + sg['t1_s'] - sg['t0_s'], 1)
        tr = _load(d, 'transcript.json')
        if tr:
            for sg in tr['segments']:
                R['speech']['segments'] += 1; R['speech']['suspect_segments'] += bool(sg['suspect']); R['speech']['translated_segments'] += (sg['lang'] != 'en' and not sg['suspect'])
                if not sg['suspect']: R['speech']['words_by_language'][sg['lang']] = R['speech']['words_by_language'].get(sg['lang'], 0) + len(sg['words'])
        al = _load(d, 'alignment.json')
        if al: R['alignment']['words'] += al['summary']['words']; R['alignment']['words_ok'] += al['summary']['ok']; R['alignment']['gaps'] += al['summary']['gaps']; R['alignment']['safe_cuts'] += al['summary']['safe']
        ex = _load(d, 'exposure.json')
        if ex:
            sm = ex['summary']; R['exposure']['mean_lin_min'] = min(filter(None, [R['exposure']['mean_lin_min'], sm['mean_lin_min']])); R['exposure']['mean_lin_max'] = max(filter(None, [R['exposure']['mean_lin_max'], sm['mean_lin_max']]))
            R['exposure']['max_range_stops'] = max(R['exposure']['max_range_stops'], round(sm['mean_lin_range_stops'], 2))
    if lufs: R['audio']['lufs_min'], R['audio']['lufs_max'] = min(lufs), max(lufs)
    R['duration_s'] = round(R['duration_s'], 1)
    json.dump(R, open(os.path.join(config.race_dir(a.name), 'report.json'), 'w'), indent=1)
    md = [f"# Race report: {a.name}", '', f"- {R['clips']} clips, {R['duration_s'] / 60:.1f} min of footage, {R['dropped_frames']} dropped frames; colour modes {R['colour_modes']}",
          f"- UTC span {R['first_utc']} to {R['last_utc']} (status {R['utc_status']})",
          f"- audio: loudness {R['audio']['lufs_min']} to {R['audio']['lufs_max']} LUFS, {R['audio']['clips_with_clipping']} clips with clipped samples; labelled seconds {R['audio']['label_seconds']}",
          f"- speech: {R['speech']['segments']} segments ({R['speech']['suspect_segments']} suspect), words {R['speech']['words_by_language']}, {R['speech']['translated_segments']} translated",
          f"- word alignment: {R['alignment']['words_ok']}/{R['alignment']['words']} words reliable, {R['alignment']['safe_cuts']}/{R['alignment']['gaps']} word gaps are safe cut points",
          f"- exposure: scene brightness {R['exposure']['mean_lin_min']} to {R['exposure']['mean_lin_max']}, largest within-clip range {R['exposure']['max_range_stops']} stops", '']
    open(os.path.join(config.race_dir(a.name), 'report.md'), 'w').write('\n'.join(md)); print('\n'.join(md))


def install_hint():
    return {'darwin': 'brew install ffmpeg exiftool', 'win32': 'winget install Gyan.FFmpeg OliverBetz.ExifTool'}.get(sys.platform, 'sudo apt-get install ffmpeg libimage-exiftool-perl   (or your distribution\'s equivalent)')


def cmd_doctor(a):
    import importlib, shutil, warnings
    ok = True
    def line(level, what, hint=''):
        nonlocal ok; ok &= level != 'FAIL'; print(f'  {level:4s} {what}' + (f'   -> {hint}' if hint and level != 'ok' else ''))
    print('tools:')
    for t, need in (('ffmpeg', True), ('ffprobe', True), ('exiftool', False), ('say', False)):
        p = shutil.which(t); line('ok' if p else ('FAIL' if need else 'warn'), f'{t}: {p or "not found"}', install_hint() if t != 'say' else 'optional: the macOS voice-over engine')
    enc = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, text=True).stdout if shutil.which('ffmpeg') else ''
    from strata360 import hw
    hwenc = hw._hardware('hevc'); line('ok' if hwenc else 'warn', f'hardware HEVC encoder ({sys.platform}): {hwenc or "none, using software libx265"}', '' if hwenc else 'renders use libx265 (slower but works everywhere)')
    line('ok' if 'libx265' in enc else 'FAIL', 'libx265 encoder', 'install an ffmpeg build with libx265' if 'libx265' not in enc else '')
    try: import hashlib; hashlib.blake2b(); line('ok', 'python hashlib has blake2 (OpenSSL build)')
    except Exception: line('warn', 'python hashlib lacks blake2b/blake2s (Python built without OpenSSL): harmless but prints error noise on every start', 'reinstall Python with OpenSSL, e.g. brew install openssl then pyenv install 3.13')
    print(f'python {sys.version.split()[0]} ({sys.executable})' + ('' if sys.version_info[:2] == (3, 13) else '  (tested on 3.13)'))
    for m, need in (('numpy', True), ('scipy', True), ('cv2', True), ('torch', True), ('faster_whisper', True), ('transformers', True), ('sentencepiece', True), ('df', False), ('torchaudio', False), ('skimage', False)):
        try: mod = importlib.import_module(m); line('ok', f'{m} {getattr(mod, "__version__", "")}')
        except Exception as e: line('FAIL' if need else 'warn', f'{m}: {type(e).__name__}', 'scripts/setup_env.sh')
    try:
        import numpy as np
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always'); r = np.random.default_rng(0); x = r.standard_normal((80, 513)).astype('float32') @ np.abs(r.standard_normal((513, 3000))).astype('float32')
        line('FAIL' if (w or not np.isfinite(x).all()) else 'ok', 'numpy matmul is clean (no BLAS warnings)', 'this Mac needs numpy\'s OpenBLAS wheel: scripts/setup_env.sh installs it')
    except Exception as e: line('warn', f'numpy check failed: {e}')
    print('models (cached under ~/.cache/huggingface; downloaded on first use):')
    hf = os.path.expanduser('~/.cache/huggingface/hub')
    for name, pat in (('whisper large-v3-turbo', 'models--*large-v3-turbo*'), ('whisper small', 'models--Systran--faster-whisper-small'), ('OPUS-MT fr-en', 'models--Helsinki-NLP--opus-mt-fr-en'),
                      ('OPUS-MT nl-en', 'models--Helsinki-NLP--opus-mt-nl-en'), ('OPUS-MT de-en', 'models--Helsinki-NLP--opus-mt-de-en'), ('wav2vec2 English aligner', 'models--facebook--wav2vec2-base-960h')):
        line('ok' if glob.glob(os.path.join(hf, pat)) else 'warn', name, 'downloads automatically the first time a run needs it')
    line('ok' if os.path.isdir(os.path.expanduser('~/Library/Caches/DeepFilterNet')) or glob.glob(os.path.join(os.path.dirname(sys.executable), '..', 'lib', '*', 'site-packages', 'df')) else 'warn', 'DeepFilterNet (optional enhancer)')
    line('ok' if os.path.exists(os.path.join(os.path.dirname(__file__), '..', '..', '.venv-cv', 'bin', 'python')) else 'warn', 'MossFormer2 environment .venv-cv (optional enhancer)', 'scripts/setup_env.sh --with-cv')
    print('races folder:'); rr = config.races_root(); os.makedirs(rr, exist_ok=True); free = shutil.disk_usage(rr).free / 1e9
    line('ok' if free > 50 else 'warn', f'{os.path.abspath(rr)}: {free:.0f} GB free', 'proxies are about 37 GB per hour of footage')
    print('all required checks passed' if ok else 'some required checks FAILED'); sys.exit(0 if ok else 1)


def cmd_fetch_models(a):
    """Download the models the default stages need (about 6 GB), so the first real run does not stall. Everything is cached locally."""
    import warnings; warnings.filterwarnings('ignore')
    cfg = config.load(a.race) if a.race else config.DEFAULTS
    from faster_whisper import WhisperModel
    print('whisper', cfg['whisper_model']); WhisperModel(cfg['whisper_model'], device='cpu', compute_type='int8')
    from transformers import MarianMTModel, MarianTokenizer, Wav2Vec2ForCTC, Wav2Vec2Processor
    for lang in [l for l in cfg['languages'] if l != 'en']:
        print('OPUS-MT', lang); n = f'Helsinki-NLP/opus-mt-{lang}-en'; MarianTokenizer.from_pretrained(n); MarianMTModel.from_pretrained(n)
    from strata360.audio import wordtimes
    for lang in cfg['align_languages']:
        print('aligner', lang); n = wordtimes.LANGUAGE_MODELS[lang]; Wav2Vec2Processor.from_pretrained(n); Wav2Vec2ForCTC.from_pretrained(n)
    print('done')


def cmd_who(a):
    from strata360.analysis import identity
    S, sug = identity.run(config.race_dir(a.name), me=a.me, label=a.label, auto=a.auto)
    print(f'{len(S)} face clusters (sheet: {config.race_dir(a.name)}/people/clusters.png)')
    for s in S: print(f"  #{s['cluster']:<3} {s['n']:5d} faces in {s['clips']:2d} clips   rear-lens share {s['rear_fraction']:.0%}   median size {s['median_size_px']:.0f} px")
    ids = ','.join(str(c) for c in sug['clusters'])
    print(f"suggested wearer: {ids}  ({'confident' if sug['confident'] else 'NOT confident, please check the sheet'}). {sug['why']}")
    if not a.me: print(f"  {'saved by --auto' if (a.auto and sug['confident']) else 'confirm with'}: ./strata360 who {a.name} --me {ids}")


def cmd_clock(a):
    """Camera clock correction (README 6.1). Anchors tie a moment in a clip to a true time; the natural one is the moment the running starts."""
    from strata360.gps import anchors as A, track
    cfg = config.load(a.name); rd = config.race_dir(a.name); tp = config.track_path(a.name, cfg); tr = track.load(tp) if tp else None
    if tr is None: sys.exit('no race track: put it at <project>/track.fit or track.gpx (the web app has an upload) or set "gps" in race.json')
    ck = cfg.setdefault('camera_clock', {}); cur = float(ck.get('offset_seconds', 0.0)) + 3600 * float(ck.get('utc_offset_hours', 0.0))
    if a.suggest or a.auto:
        res = A.suggest(rd, tr, prior_s=cur)
        if a.json: print(json.dumps(dict(current_offset_s=cur, suggestions=res)))
        print(f'current offset {cur:+.0f} s (camera minus UTC). Votes from running starts/stops seen by both the camera and the GPS:')
        for r in ([] if a.json else res): print(f"  offset {r['offset_s']:+8.1f} s   score {r['score']:6.2f}  {r['votes']:3d} votes  confidence {r['confidence']:.0%}   clips {', '.join(r['clips'])}")
        if res and not a.json: print('apply the best with: ./strata360 clock', a.name, '--use-suggestion 1  (or --auto)')
        if a.auto and res and res[0]['confidence'] >= 0.7 and res[0]['votes'] >= 3: a.use_suggestion = 1
        elif a.auto: print('auto: not confident enough (need >= 3 votes and >= 70% confidence); pick with --use-suggestion or set an anchor')
    if a.use_suggestion:
        r = A.suggest(rd, tr)[a.use_suggestion - 1]; ck['utc_offset_hours'] = 0.0; ck['offset_seconds'] = r['offset_s']; ck['verified'] = True
        ck['note'] = f"from {r['votes']} matching running start/stop events (clock --suggest); check with an anchor"; config.save(a.name, cfg); print('offset set to', r['offset_s'], 's; re-timing clips'); a.apply = True
    if a.anchor:
        clip, t = a.anchor.split(':'); an = A.add_anchor(rd, tr, clip, float(t), utc=a.utc, kind=a.kind, current_offset_s=cur)
        print(json.dumps(an, indent=1))
        if an['ambiguous'] and not a.utc: print('WARNING: several GPS events fit; the nearest to the current estimate was used. Give --utc to be sure.')
        ck.setdefault('anchors', []).append(an); config.save(a.name, cfg); a.apply = True
    if a.list:
        for i, x in enumerate(ck.get('anchors', [])): print(i, x['clip'][-6:], f"t={x['t_s']}s", x['kind'], 'utc', x['utc'], 'offset', x['offset_s'])
    if a.apply and ck.get('anchors'):
        m = A.apply_to_config(cfg, ck['anchors']); config.save(a.name, cfg); print('clock model:', m)
    if a.apply:
        res = runner.run(a.name, ['ingest'], None, False); print('re-timed:', {k: v for k, v in __import__('collections').Counter(res.values()).items()})


def project_progress(name):
    name_ = name
    """Everything a GUI needs to draw the start screen and the progress bar (also `strata360 progress FOLDER --json`).
    state: new (no project yet), processing (stages still to do), needs_input (waiting for the user: wearer profile / clock), complete."""
    rd = config.race_dir(name)
    if not os.path.exists(os.path.join(rd, 'race.json')):
        return dict(state='new', folder=str(name), project=rd)
    cfg = config.load(name); cl, other = clipmod.discover(cfg['library']); names = [n for n in ORDER if n in cfg['stages']]; stages = []; done_all = 0; total_all = 0; eta = 0.0; health = runner.stage_health(name)
    for n in names:
        done = 0; secs = []
        for c in cl:
            st = runner.load_state(name, c.id); sym = _state_symbol(name, cfg, c, n, st); done += sym == 'ok'
            if sym == 'ok' and st.get(n, {}).get('seconds'): secs.append(st[n]['seconds'])
        per = float(np.mean(secs)) if secs else None; left = (len(cl) - done) * per if per else None; eta += left or 0.0
        stages.append(dict(name=n, retry=health.get(n), running=[dict(clip=c_, pid=p_) for c_, s_, p_ in runner.active_items(name_) if s_ == n], waiting=('the race track' if (STAGES[n].needs_track and config.track_path(name_, cfg) is None) else None), done=int(done), total=len(cl), seconds_per_clip=None if per is None else round(per, 1), eta_s=None if left is None else round(left), note=STAGES[n].note)); done_all += done; total_all += len(cl)
    needs = []
    tr_missing = config.track_path(name, cfg) is None and any(STAGES[n].needs_track for n in names)
    if tr_missing: needs.append('race_track')
    if 'identity' in names and not os.path.exists(os.path.join('profiles', cfg.get('profile', 'me') + '.npz')): needs.append('wearer_profile')
    if not cfg.get('camera_clock', {}).get('verified'): needs.append('camera_clock')
    from strata360.pipeline import resources
    wk = runner.workers(name); resources_ok = resources.may_start_extra_worker(len(wk), cfg); lock = bool(wk); act = runner.active_items(name); by_pid = {p_: (c_, s_) for c_, s_, p_ in act}
    blocked = ({'identity'} if 'wearer_profile' in needs else set()) | ({n for n in names if STAGES[n].needs_track} if tr_missing else set())                                                # stages that cannot run until the user has chosen who they are
    pending = any(s_['done'] < s_['total'] for s_ in stages if s_['name'] not in blocked)
    state = 'processing' if (lock or pending) else ('needs_input' if (needs or any(s_['done'] < s_['total'] for s_ in stages)) else 'complete')
    return dict(state=state, folder=cfg['library'], project=rd, clips=len(cl), footage_gb=round(sum(c.size for c in cl) / 1e9, 1), unsupported=len(other), running=lock, can_add_worker=resources_ok[0], add_worker_reason=resources_ok[1], workers=len(wk), worker_list=[dict(pid=p_, clip=(by_pid.get(p_) or (None, None))[0], stage=(by_pid.get(p_) or (None, None))[1]) for p_ in wk], runnable=runner.runnable_count(name), active=[dict(clip=c, stage=s) for c, s, _ in act],
                percent=round(100.0 * done_all / max(total_all, 1), 1), eta_s=round(eta), stages=stages, needs=needs, has_gps=bool(config.track_path(name, cfg)))


def cmd_progress(a):
    p = project_progress(a.name)
    if a.json: print(json.dumps(p)); return
    if p['state'] == 'new': print(f"no project in {p['folder']} yet: ./strata360 open {p['folder']}"); return
    print(f"{p['state']}: {p['clips']} clips, {p['footage_gb']} GB, {p['percent']}% of stage work done" + (f", about {p['eta_s'] / 60:.0f} min left" if p['eta_s'] else '') + (' (running)' if p['running'] else ''))
    for s in p['stages']: print(f"  {s['name']:11s} {s['done']:3d}/{s['total']:<3d} {'#' * int(20 * s['done'] / max(s['total'], 1)):<20s}" + (f"  ~{s['eta_s'] / 60:.0f} min left" if s['eta_s'] else ''))
    if p['needs']: print('  waiting for you:', ', '.join(p['needs']))


def cmd_plan_blocks(a):
    from strata360.edit import project as PJ
    r = PJ.rough_blocks(a.name, a.target_s, a.auto)
    if a.json: print(json.dumps(r, indent=1)); return
    p = r['plan']; src = {'music': f"the music track ({r['music']['duration_s']:.0f} s long, from its first bar at {r['music']['offset_s']:.1f} s)" if r['music'] else '', 'target': f"the target you gave ({a.target_s} s)", 'automatic': 'automatic (from the usable footage)'}[r['target_source']]
    print(f"film length guide: {src}\nrough plan: {len(p['blocks'])} blocks, {p['target_s']:.1f} s, {len(p['dropped'])} clip(s) dropped" + (f", short by {p['shortfall_s']:.1f} s" if p['shortfall_s'] else ''))
    print(f"{'#':>3} {'clip':27} {'target':>7} {'usable':>7} {'speech':>7} {'min':>5} {'max':>6}  preferred")
    for b in p['blocks']:
        kinds = {}
        for x in b['preferred']: kinds[x['kind']] = kinds.get(x['kind'], 0) + 1
        print(f"{b['index']:>3} {b['clip']:27} {b['target_s']:>7.1f} {b['usable_s']:>7.1f} {b['dialogue_s']:>7.1f} {b['min_s']:>5.1f} {b['max_s']:>6.1f}  " + ' '.join(f'{k}x{n}' for k, n in kinds.items()))
    for d in p['dropped']: print(f"dropped {d['clip']}: {d['reason']}")
    for w in p['warnings']: print('warning:', w)
    if r['clips_without_candidates']: print(f"{len(r['clips_without_candidates'])} clip(s) have no candidates yet and are not in the plan")


def cmd_coverage(a):
    from strata360.pipeline.coverage import coverage
    r = coverage(a.name)
    if a.json: print(json.dumps(r)); return
    print(f"{r['clips']} clips; default-stage artefacts present:")
    for n in r['stages']: print(f"  {n:15s} {r['totals'][n]:3d}/{r['clips']}")
    if r['complete']: print('nothing missing for the default stages'); return
    print('missing:')
    for m in r['missing']: print(f"  {m['clip']}  {m['stage']} ({m['state']})")
    print('decisions blocked:')
    for x, cs in r['blocked'].items(): print(f"  {x}: {len(cs)} clip(s)")


def cmd_open(a):
    """The GUI's first screen in command form: pick a footage folder; the project (<folder>/strata360/) is created if needed, whatever is already done is kept, and the rest
    is processed. When everything is complete the next step is the results / export stage."""
    folder = os.path.abspath(a.name); rd = config.race_dir(folder)
    if not os.path.isdir(folder): sys.exit(f'not a folder: {folder}')
    if not os.path.exists(os.path.join(rd, 'race.json')):
        cfg = json.loads(json.dumps(config.DEFAULTS)); cfg['name'] = os.path.basename(folder); cfg['library'] = folder
        if a.languages: cfg['languages'] = a.languages.split(',')
        if a.gps: cfg['gps'] = os.path.abspath(a.gps)     # copied to the known filename below
        os.makedirs(rd, exist_ok=True); config.save(folder, cfg); cl, other = clipmod.discover(folder)
        print(f'new project {rd}: {len(cl)} clips ({sum(c.size for c in cl) / 1e9:.1f} GB)')
    elif a.gps:
        cfg = config.load(folder); cfg['gps'] = os.path.abspath(a.gps); config.save(folder, cfg)
    if a.gps:                                                                        # the race track lives at the known filename in the project folder
        import shutil; ext = os.path.splitext(a.gps)[1].lower()
        if ext in ('.fit', '.gpx'): shutil.copyfile(a.gps, os.path.join(rd, 'track' + ext)); print('race track saved as', os.path.join(rd, 'track' + ext))
    p = project_progress(folder); print(f"state: {p['state']}, {p['percent']}% done" + (f", about {p['eta_s'] / 60:.0f} min left" if p['eta_s'] else ''))
    if p['state'] in ('processing',) and not a.no_run:                                # a worker: it loops until nothing is left; more can run at once (each picks unfinished, unclaimed items)
        if worker_allowed(folder): runner.run(folder, None, None, False); p = project_progress(folder)
    if p['state'] == 'complete': print('everything is processed: next is the results / export stage')
    if p['needs']: print('waiting for you:', ', '.join(p['needs']), '(wearer_profile: ./strata360 who FOLDER --auto; camera_clock: ./strata360 clock FOLDER --suggest)')


def cmd_serve(a):
    from strata360.server import app
    app.main(sum([['--root', r] for r in (a.root or [])], []) + ['--host', a.host, '--port', str(a.port)] + (['--token', a.token] if a.token else []) + (['--reload'] if a.reload else []))


def cmd_voice(a):
    """Which voice is the wearer's (the cameraman talking to the camera) and which is chatter around them."""
    from strata360.analysis import voices
    rd = config.race_dir(a.name); E, meta = voices.collect(rd)
    if not len(E): sys.exit('no speaker data yet: ./strata360 run RACE --stages speakers')
    lab = voices.cluster(E); S = voices.summarise(E, meta, lab); sug = voices.suggest_wearer(S)
    print(f'{len(E)} speech segments in {len({m["clip"] for m in meta})} clips, {len(set(lab))} voices; the biggest:')
    for s in S: print(f"  #{s['cluster']:<4} {s['n']:4d} segments {s['seconds']:6.1f} s in {s['clips']:2d} clips  level {s['median_rms_db']:6.1f} dBFS   e.g. " + ' | '.join(t[:40] for t in s['samples'][:2]))
    print(f"suggested wearer voice: #{sug['cluster']} ({'confident' if sug.get('confident') else 'NOT confident, check the lines above'}). {sug['why']}")
    me = a.me or (str(sug['cluster']) if (a.auto and sug.get('confident')) else None)
    if me:
        n = voices.save_profile(E, lab, [int(x) for x in str(me).split(',')], f'profiles/{a.label}_voice.npz'); print(f'saved profiles/{a.label}_voice.npz from {n} segments; re-run speakers to label them: ./strata360 run {a.name} --stages speakers --force')
    else: print(f'confirm with: ./strata360 voice {a.name} --me {sug["cluster"]}')


def cmd_transcript_fix(a):
    """Ask the language model for corrections to the recognised words; progress in <project>/transcript_fix.json (the app shows it)."""
    from strata360.analysis import transcript_fix as TF
    sp = os.path.join(config.race_dir(a.name), 'transcript_fix.json')
    def status(state, done=0, total=0, fixes=0, **kw):
        tmp = sp + '.tmp'; json.dump(dict(state=state, pid=os.getpid(), done=done, total=total, fixes=fixes, **kw), open(tmp, 'w')); os.replace(tmp, sp)
    status('running')
    try:
        if a.text_only: r = TF.run(a.name, clips=a.clip, provider=a.provider, model=a.model, progress=lambda i, n, k: status('running', i, n, k))
        else: r = TF.run_audio(a.name, clips=a.clip, provider=a.provider, model=a.model, runs=a.checks, thinking=a.thinking)
    except Exception as e: status('error', error=f'{type(e).__name__}: {e}'); raise
    status('done', len(r), len(r), sum(r.values())); print(f'{sum(r.values())} suggested corrections in {len(r)} clips')


def cmd_voiceover(a):
    from strata360.edit import voiceover as VO
    f = a.name
    if a.fetch: VO.fetch_model(); print('voice model ready in', os.path.abspath(VO.MODEL_DIR)); return
    if a.list:
        for e in VO.available_engines(): print(e['id'], '-', e['label']); [print('   ', v['name'], v['lang']) for v in e['voices']]
        return
    for _ in range(8):                                                                   # a script, voice or speed chosen while speaking is made next
        d = VO.build(f, engine=a.engine, voice=a.voice, rate=a.rate, progress=lambda i, n: print(f'\rspeaking {i}/{n}', end='', flush=True)); print()
        st = VO.load_state(f)
        if VO.newest_script(f) == d['script'] and (st['voice'] in (None, d['voice'])) and st['rate'] == d['rate']: break          # a voice, speed or script chosen meanwhile is made next
    print(f"{d['engine']} / {d['voice']}: {len(d['lines'])} lines, measured {d['measured_wpm']} words/min; sped up: {d['sped']}; too long: {d['over']}\n-> {os.path.join(VO.base(f), 'voiceover.wav')}")


def cmd_final(a):
    from strata360.render import final
    sys.argv = ['final', a.name, '--size', a.size, '--fps', str(a.fps), '--bitrate', a.bitrate] + (['--pieces', str(a.pieces)] if a.pieces else []) + (['--out', a.out] if a.out else []); final.main()


def cmd_film(a):
    from strata360.render import preview
    sys.argv = ['film', a.name] + (['--px', str(a.px)] if a.px else []) + (['--force'] if a.force else []); preview.main()


def cmd_script(a):
    """Propose a voice-over script: plan a film of the target length from the candidates, then a local LLM writes narration per segment from the notes, transcript and track data."""
    import datetime as dt
    from strata360.pipeline import notes as N
    from strata360.edit import techniques as TQ, optimise as O, script as SC
    from strata360.gps import track
    cfg = config.load(a.name); rd = config.race_dir(a.name); notes = N.load(a.name); tp = config.track_path(a.name, cfg); tr = track.load(tp) if tp else None
    from strata360.edit import project as PJ
    cdir = os.path.join(rd, 'clips'); cands = {}
    try:                                                                                          # the saved plan (what the timeline shows); a new one only if there is none or another length was asked for
        cur = PJ.load(a.name); plan_len = ((cur.get('plan') or {}).get('film') or {}).get('length_s')
        if not cur.get('plan') or (a.length and abs(a.length - plan_len) > 0.6) or (a.seed is not None and a.seed != cur['settings']['seed'] and a.reseed):
            PJ.propose(a.name, dict(length_s=a.length or cur['settings']['length_s'], seed=a.seed if a.seed is not None else cur['settings']['seed']))
        edit = PJ.load(a.name)
    except O.Infeasible as e: sys.exit(str(e))
    plan_doc = edit['plan']; length = plan_doc['film']['length_s']; beat_s = 60.0 / plan_doc['film']['bpm']
    for f in sorted(glob.glob(os.path.join(cdir, '*', 'candidates.json'))):
        for c in json.load(open(f))['candidates']: cands[c['id']] = c
    if plan_doc.get('missing_clips'): print(f"WARNING: {len(plan_doc['missing_clips'])} clip(s) have no candidates yet (their stages are unfinished) and are not in this plan")
    facts = []
    for g in plan_doc['segments']:
        cd = cands.get(g['cand_id']) or dict(id=g['cand_id'], clip=g['clip'], start_s=g['cand_start_s'], end_s=g['cand_end_s'], start_utc=g['utc_start'], features={}, people=None)
        facts.append(SC.segment_facts(dict(id=g['id'], index=g['index'], start_s=g['film_start_s'], dur_s=g['dur_s'], technique=g['technique'], in_s=g['in_s']), cd, cdir, tr, notes, cfg.get('timezone', 'Europe/Brussels')))
    a.length = length
    race_line = ''
    if tr is not None:
        race_line = f"The race: {tr['dist'][-1] / 1000:.0f} km over {(tr['t'][-1] - tr['t'][0]) / 3600:.0f} hours."
    from strata360.pipeline import meta as MT
    race_line = (MT.describe(a.name) + ' ' + race_line).strip()
    print(f'planned {len(plan_doc["segments"])} segments for {a.length:.0f} s; writing the script ({(a.provider or (cfg.get("llm") or {}).get("provider", "vertex"))})...')
    llm = dict(cfg.get('llm') or {}); prov = a.provider or llm.get('provider', 'vertex'); model = a.model or (llm.get('model') if llm.get('provider', 'vertex') == prov else None)
    doc = SC.write_script(facts, notes['folder'], a.length, wpm=a.wpm, style=a.style or '', race_line=race_line, work_dir=rd, model=model if prov != 'local' else None, provider=prov)
    os.makedirs(os.path.join(rd, 'scripts'), exist_ok=True); p = os.path.join(rd, 'scripts', 'script-' + dt.datetime.now().strftime('%Y%m%d-%H%M%S') + '.json'); json.dump(dict(doc, facts=facts), open(p, 'w'), indent=1)
    print(f"\n{doc.get('title') or '(untitled)'}   {doc['total_words']} words, about {doc['total_speak_s']} s of speech in {a.length:.0f} s   [{doc['seconds_llm']} s LLM]")
    for l in doc['lines']: print(f"  [{l['seg']:2d}] {l['film_start_s']:5.1f}s +{l['seconds']:4.1f}s {l['clip'][-6:]}  " + (l['text'] or '—'))
    if doc['remaining_problems']: print('remaining problems:', doc['remaining_problems'])
    print('saved', p)
    try:                                                                                 # a new script is spoken at once (a separate step: its status is shown in the app)
        from strata360.edit import voiceover as VO
        VO.build(a.name); print('voice-over spoken')
    except Exception as e: print(f'voice-over not made: {e}')


def cmd_clear(a):
    """Forget the status of a stage (and, unless --no-cascade, the stages that depend on it) so it is processed again."""
    done = runner.clear(a.name, a.stage, a.clip and [c for c in a.clip.split(',')], cascade=not a.no_cascade)
    print(f'cleared {len(done)} item(s): ' + ', '.join(sorted({s for _, s in done})) + ('' if done else ' (nothing had a status)'))
    print(f'run ./strata360 run {a.name} (or start processing in the app) to redo them')


def cmd_set_key(a):
    """Store the Anthropic API key for the script writer (mode 600 in ~/.strata360; never in the project or the repo). Typed without echo; --clear removes it."""
    import getpass
    from strata360.edit import llm_remote as L
    if a.clear: L.set_key('', a.provider); print('key removed'); return
    k = getpass.getpass(f'{a.provider} API key (input hidden): '); L.set_key(k, a.provider); print('saved to secrets.env (gitignored)')


def cmd_render(a):
    from strata360.render import flat
    sys.argv = ['render'] + a.args; flat.main()


def cmd_stop_all(a):
    from strata360.pipeline import guard
    killed = guard.panic(); print(f'killed {len(killed)} processes' + (f': {killed[:20]}' if killed else '')); print(f'memory pressure level {guard.pressure_level()}, swap {guard.swap_used_gb():.1f} GB, load {os.getloadavg()[0]:.1f}')


def main():
    ap = argparse.ArgumentParser(prog='strata360', description='Automatic editing pipeline for 360 race footage'); sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('init', help='create a race from a folder of camera files'); p.add_argument('name'); p.add_argument('--library', required=True)
    p.add_argument('--languages'); p.add_argument('--align-languages'); p.add_argument('--whisper-model'); p.add_argument('--clock-offset-hours', type=float, default=0.0)
    p.add_argument('--clock-verified', action='store_true'); p.add_argument('--clock-note'); p.add_argument('--force', action='store_true'); p.set_defaults(fn=cmd_init)
    p = sub.add_parser('catalog', help='list the clips in the library'); p.add_argument('name'); p.set_defaults(fn=cmd_catalog)
    p = sub.add_parser('run', help='run stages over the clips (cached; safe to repeat)'); p.add_argument('name'); p.add_argument('--stages', help=f'comma list of {ORDER}'); p.add_argument('--clips', help='substring or glob of clip ids')
    p.add_argument('--force', action='store_true'); p.add_argument('--fail-fast', action='store_true'); p.set_defaults(fn=cmd_run)
    p = sub.add_parser('status', help='what is done per clip and stage'); p.add_argument('name'); p.add_argument('--all', action='store_true'); p.add_argument('--errors', action='store_true'); p.set_defaults(fn=cmd_status)
    p = sub.add_parser('show', help='summarise one clip'); p.add_argument('name'); p.add_argument('clip'); p.set_defaults(fn=cmd_show)
    p = sub.add_parser('report', help='race-level summary (report.json and report.md)'); p.add_argument('name'); p.set_defaults(fn=cmd_report)
    p = sub.add_parser('doctor', help='check the environment'); p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser('stop-all', help='emergency stop: kill every ffmpeg, ffprobe, pytest and strata360 process of this user (not the web server)'); p.set_defaults(fn=cmd_stop_all)
    p = sub.add_parser('fetch-models', help='download the models the default stages need'); p.add_argument('race', nargs='?'); p.set_defaults(fn=cmd_fetch_models)
    p = sub.add_parser('who', help='cluster the faces, show them, and save which one is you'); p.add_argument('name'); p.add_argument('--me', help='cluster number(s) that are you, comma separated: 101 or 101,103'); p.add_argument('--label', default='me'); p.add_argument('--auto', action='store_true', help='save the suggested wearer as the profile if the suggestion is confident'); p.set_defaults(fn=cmd_who)
    p = sub.add_parser('clock', help='camera clock: suggest an offset from running starts, or set it from an anchor (clip + moment + true time)'); p.add_argument('name')
    p.add_argument('--suggest', action='store_true'); p.add_argument('--auto', action='store_true', help='suggest and apply the best if it is clearly ahead'); p.add_argument('--json', action='store_true', help='machine-readable output (for the GUI)'); p.add_argument('--use-suggestion', type=int, metavar='N'); p.add_argument('--anchor', metavar='CLIP:SECONDS', help='clip id (or its last digits) and a moment in it, e.g. 0004:48')
    p.add_argument('--utc', help='true UTC of that moment (ISO); default: the matching running start/stop in the GPS file'); p.add_argument('--kind', choices=['start', 'stop']); p.add_argument('--list', action='store_true'); p.add_argument('--apply', action='store_true')
    p.set_defaults(fn=cmd_clock)
    p = sub.add_parser('open', help='open a footage folder as a project: create it if new, continue whatever is unfinished (what the GUI does first)'); p.add_argument('name', metavar='FOLDER')
    p.add_argument('--languages'); p.add_argument('--gps', help='the race FIT/GPX'); p.add_argument('--no-run', action='store_true'); p.set_defaults(fn=cmd_open)
    p = sub.add_parser('progress', help='project state and per-stage progress (--json for the GUI)'); p.add_argument('name', metavar='FOLDER_OR_RACE'); p.add_argument('--json', action='store_true'); p.set_defaults(fn=cmd_progress)
    p = sub.add_parser('plan-blocks', help='the rough plan: one block per clip with its target length, usable footage and dialogue (the film length from --target-s, else the music track, else automatic)'); p.add_argument('name', metavar='FOLDER_OR_RACE'); p.add_argument('--target-s', type=float, help='film length guide in seconds'); p.add_argument('--auto', action='store_true', help='ignore the music track: automatic length'); p.add_argument('--json', action='store_true'); p.set_defaults(fn=cmd_plan_blocks)
    p = sub.add_parser('coverage', help='which analysis artefacts exist per clip and which decisions the missing ones block (--json for the GUI)'); p.add_argument('name', metavar='FOLDER_OR_RACE'); p.add_argument('--json', action='store_true'); p.set_defaults(fn=cmd_coverage)
    p = sub.add_parser('final', help='render the final film at full quality from the original video (resumable; slow)'); p.add_argument('name', metavar='FOLDER'); p.add_argument('--size', default='3840x2160'); p.add_argument('--fps', type=float, default=50.0); p.add_argument('--bitrate', default='100M'); p.add_argument('--pieces', type=int); p.add_argument('--out'); p.set_defaults(fn=cmd_final)
    p = sub.add_parser('film', help='render the streaming preview of the planned film (plan + framing + voice-over)'); p.add_argument('name', metavar='FOLDER'); p.add_argument('--px', type=int); p.add_argument('--force', action='store_true'); p.set_defaults(fn=cmd_film)
    p = sub.add_parser('serve', help='web server: browse footage folders (inside allowed roots) and drive processing from a browser'); p.add_argument('--root', action='append'); p.add_argument('--host', default='127.0.0.1'); p.add_argument('--port', type=int, default=8360); p.add_argument('--token'); p.add_argument('--reload', action='store_true', help='restart on code changes'); p.set_defaults(fn=cmd_serve)
    p = sub.add_parser('voice', help='find the wearer\'s own voice among the speakers (vs chatter around them)'); p.add_argument('name'); p.add_argument('--me'); p.add_argument('--auto', action='store_true'); p.add_argument('--label', default='me'); p.set_defaults(fn=cmd_voice)
    p = sub.add_parser('transcript-fix', help='ask the language model (Gemini) to suggest corrections to the recognised words'); p.add_argument('name', metavar='FOLDER'); p.add_argument('--clip', action='append'); p.add_argument('--provider'); p.add_argument('--model'); p.add_argument('--text-only', action='store_true', help='only send the words, not the audio'); p.add_argument('--checks', type=int, default=3, help='checks per excerpt; a fix needs 2 of them'); p.add_argument('--thinking', default='low'); p.set_defaults(fn=cmd_transcript_fix)
    p = sub.add_parser('voiceover', help='speak the script with a local voice and mix the voice-over track (recordings replace lines)'); p.add_argument('name', metavar='FOLDER'); p.add_argument('--engine'); p.add_argument('--voice'); p.add_argument('--rate', type=int); p.add_argument('--list', action='store_true', help='list engines and voices'); p.add_argument('--fetch', action='store_true', help='download the voice model (Kokoro, about 350 MB)'); p.set_defaults(fn=cmd_voiceover)
    p = sub.add_parser('script', help='propose a voice-over script for a film of the target length (notes + transcript + track data -> local LLM)'); p.add_argument('name', metavar='FOLDER_OR_RACE')
    p.add_argument('--length', type=float, default=None, help='film length in seconds (default: the saved plan\'s)'); p.add_argument('--wpm', type=float, default=145.0); p.add_argument('--style', help='e.g. "dry, self-deprecating, British"'); p.add_argument('--seed', type=int, default=None); p.add_argument('--reseed', action='store_true', help='re-plan with the given seed'); p.add_argument('--provider', choices=['vertex', 'gemini', 'anthropic', 'local']); p.add_argument('--model'); p.set_defaults(fn=cmd_script)
    p = sub.add_parser('clear', help='forget the status of a stage so it is processed again (with the stages that depend on it)'); p.add_argument('name', metavar='FOLDER_OR_RACE'); p.add_argument('stage')
    p.add_argument('--clip', help='comma-separated full clip ids (default all)'); p.add_argument('--no-cascade', action='store_true'); p.set_defaults(fn=cmd_clear)
    p = sub.add_parser('set-key', help='store an API key for the voice-over script writer in secrets.env (gitignored)'); p.add_argument('--provider', choices=['vertex', 'gemini', 'anthropic'], default='vertex'); p.add_argument('--clear', action='store_true'); p.set_defaults(fn=cmd_set_key)
    p = sub.add_parser('render', help='render a flat 4K view (arguments as for the renderer)'); p.add_argument('args', nargs=argparse.REMAINDER); p.set_defaults(fn=cmd_render)
    a = ap.parse_args(); a.fn(a)


if __name__ == '__main__':
    main()
