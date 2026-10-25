"""Race configuration: one `race.json` per race collection (races/<name>/race.json), merged over these defaults.

Every stage declares which config keys it depends on (stages.py), so changing a setting re-runs only the stages that use it."""
import copy, json, os, re
from strata360 import hw

DEFAULTS = {
    'name': None,
    'library': None,                        # folder holding the camera files (searched recursively)
    'camera': 'dji_osmo_360',
    # The camera clock. `utc_offset_hours` is the camera clock's offset from UTC: 0 = the camera shows UTC (the default assumption, which
    # matched the one clip checked in M0), 1 = it shows Belgian winter local time recorded as if it were UTC. `verified` should be set to
    # true only after checking against the GPX or a known event; until then start times are reported as provisional.
    'camera_clock': {'utc_offset_hours': 0.0, 'verified': False, 'note': ''},
    'languages': ['en'],                    # languages the speech identifier may choose from (e.g. ['en', 'fr', 'nl', 'de'] in Belgium)
    'whisper_model': hw.default_whisper_model(),         # large-v3 with a CUDA GPU, else large-v3-turbo (hw.default_whisper_model)
    'align_languages': ['en'],              # languages with a forced-alignment model (wordtimes.LANGUAGE_MODELS)
    'exposure_every_frames': 10,
    'people_every_frames': 50,
    'profile': 'me',
    'scenes_every_s': 5.0,
    'scenes_px': 512,                        # the side of the front and rear pictures the scene model is shown (on 12 judged pictures: 120 degrees at 512 px 58 of 60 fields, 100 degrees at 768 px 54; the model reads a 512 picture as well and is 15% faster)
    'scenes_fov': 120.0,                     # their field of view in degrees (130 degrees at 640 px also scored 58)
    'scenes_sampling': 'adaptive',           # 'adaptive': look at the clip when the runner has moved or the scene has changed (analysis/sampling.py); 'fixed': every scenes_every_s seconds
    'transcript_check': {'mode': 'pro', 'pool': ['gemini:gemini-3.1-pro-preview'], 'pair': True, 'transcriber': False, 'min_votes': 2, 'accept': 0.5, 'thinking': 'low',
                         'patience': 3},          # Gemini Pro (paid key) checks each 60-120 s speech-only excerpt twice, a third time only when the two differ; a fix needs 2 votes (analysis/transcript_fix.py). mode 'transcribe': the transcription model alone; give a Flash 'pool' without 'pair' for the adaptive mixture. Opt-in stage `transcript_check`: paid API calls, every reply cached
    'llm': {'provider': 'gemini', 'model': 'gemini-3.1-pro-preview'},           # the voice-over script writer: Gemini Pro through a Google Cloud (Vertex AI) key in secrets.env; or 'gemini' (AI Studio key), 'anthropic', 'local' (mlx-lm)
    'places': {'radius_m': 1000},                 # OpenStreetMap lookups (README 18.4j); endpoints can be replaced by a self-hosted Nominatim / Overpass
    'overlay': {'enabled': True},           # the race overlay on the final film and the thumbnails (overlay/layout.py: elements, layout, map styles, zoom, scale, fonts); map key THUNDERFOREST_API_KEY in secrets.env
    'proxy': {'size': '3840x1920', 'every_frames': 2, 'bitrate': '16M', 'encoder': 'h264'},
    'stages': ['ingest', 'audio_extract', 'audio_clean', 'audio_events', 'motion', 'proxy', 'palette', 'thumb', 'places', 'sun', 'audio', 'transcribe', 'align', 'exposure', 'people', 'identity', 'scenes', 'speakers', 'candidates', 'thumb_best', 'thumb_overlay'],   # default set for `run` / `open`; `proxy` is opt-in (slow, large)
}


def _setting(env, key):
    """A folder setting: the environment variable, else `key` in ~/.strata360/server.json (so the server's worker processes and the command line agree), as a real path; None when unset."""
    v = os.environ.get(env)
    if not v:
        try: v = json.load(open(os.path.expanduser('~/.strata360/server.json'))).get(key)
        except (OSError, ValueError, AttributeError): v = None
    return os.path.realpath(os.path.expanduser(v)) if v else None


def footage_root(): return _setting('STRATA_FOOTAGE', 'footage')          # where the camera files are (only read)
def projects_root(): return _setting('STRATA_PROJECTS', 'projects')      # where every project's results go when set: <projects>/<footage folder's path under the footage root>/


def races_root():
    """The folder of race-name projects (`races/<name>`): STRATA_RACES, else the projects folder when one is set (so nothing is written in the code folder), else `races/` in the repository (the original layout)."""
    return os.environ.get('STRATA_RACES') or projects_root() or os.path.join(os.path.dirname(__file__), '..', '..', '..', 'races')


PROJECT_SUBFOLDER = 'strata360'      # without a projects folder, results live in <footage folder>/strata360/ (race.json, clips/, run.log, people/, ...); the GUI just asks for the footage folder


def is_project_path(name):
    return os.path.sep in str(name) or str(name).startswith('.') or os.path.isdir(os.path.join(str(name), PROJECT_SUBFOLDER))


def source(path, near):
    """Where a source file recorded in a clip.json really is on THIS machine. The path was stored where the footage was ingested (/Volumes/Expansion/... on the Mac that made the project); when it does not exist here, the file of that name beside the
    project (in `near` or any folder above it, a clip folder for instance) is used, so a project can be opened from another computer or another mount. None stays None."""
    if not path or os.path.exists(path): return path
    d = os.path.abspath(str(near)); name = re.split(r'[\\/]', str(path))[-1]; last = None            # a path made on Windows has backslashes
    while d != last:
        if os.path.isfile(os.path.join(d, name)): return os.path.join(d, name)
        if os.path.isfile(os.path.join(d, 'race.json')) and projects_root():                    # the project folder: the footage is elsewhere, in the folder it is named after
            found = _footage_index(footage_of(d)).get(name)
            if found: return found
        last, d = d, os.path.dirname(d)
    return path


_FOOTAGE_INDEX = {}


def _footage_index(folder):
    """{file name: path} of the files under a footage folder (found once per folder and process)."""
    if folder not in _FOOTAGE_INDEX:
        idx = {}
        for root, dirs, files in os.walk(folder):
            dirs[:] = [x for x in dirs if x != PROJECT_SUBFOLDER]
            for fn in files: idx.setdefault(fn, os.path.join(root, fn))
        _FOOTAGE_INDEX[folder] = idx
    return _FOOTAGE_INDEX[folder]


def _relative_to_footage(folder):
    """The path of a footage folder under the footage root: the name its project folder has under the projects folder."""
    fr = footage_root()
    if not fr: raise ValueError('a projects folder needs a footage folder too: give --footage PATH (or STRATA_FOOTAGE, or "footage" in ~/.strata360/server.json)')
    rel = os.path.relpath(os.path.realpath(os.path.abspath(str(folder))), fr)
    if rel == '.' or rel == os.pardir or rel.startswith(os.pardir + os.sep): raise ValueError(f'{folder} is not a folder inside the footage folder {fr}')
    return rel


def race_dir(name):
    """`name` is either a race name (<races root>/<name>, the old layout) or a footage folder (any path). Its results live in <projects>/<same folder name>/ when a projects folder is set, else in <folder>/strata360/."""
    if is_project_path(name):
        pr = projects_root()
        if pr: return os.path.join(pr, _relative_to_footage(name))
        return os.path.abspath(os.path.join(str(name), PROJECT_SUBFOLDER))
    return os.path.abspath(os.path.join(races_root(), name))


def footage_of(rd):
    """The footage folder whose results are in the project folder `rd` (the reverse of race_dir for a footage folder)."""
    rd = os.path.abspath(str(rd)); pr = projects_root()
    if pr and os.path.realpath(rd).startswith(pr + os.sep): return os.path.join(footage_root(), os.path.relpath(os.path.realpath(rd), pr))
    return os.path.dirname(rd) if os.path.basename(rd) == PROJECT_SUBFOLDER else rd


TRACK_NAMES = ('track.fit', 'track.gpx')      # the race track lives at <project>/track.fit or track.gpx (uploaded in the GUI or copied there)


LEGACY_PROFILE_DIRS = [os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'profiles'), 'profiles']       # where profiles were kept before they lived in the project: the repository's folder, the working folder's


def profile_path(rd, cfg=None, voice=False):
    """The wearer's face profile (`<project>/profiles/<profile>.npz`) or voice profile (`..._voice.npz`) of the project whose results folder is `rd` (race_dir): where it is saved, and where it is read from when it exists there. A profile made before they lived
    in the project (the repository's `profiles/` folder, or the working folder's) is still found, so a project that has none of its own keeps working; copy it into the project to make the project complete on its own."""
    name = f"{(cfg or {}).get('profile', 'me')}{'_voice' if voice else ''}.npz"; mine = os.path.join(rd, 'profiles', name)
    if os.path.exists(mine): return mine
    for d in LEGACY_PROFILE_DIRS:
        if os.path.exists(os.path.join(d, name)): return os.path.abspath(os.path.join(d, name))
    return mine


def track_path(name, cfg=None):
    """The race track file of a project: the known filename in the project folder, else the (older) `gps` setting, else None."""
    from strata360.gps import tracks                                       # the one track the program uses: the run, or the runs merged (route tracks are for the overview map only)
    p = tracks.current_path(race_dir(name))
    if p: return p
    g = (cfg or {}).get('gps')
    return g if g and os.path.exists(g) else None


ADDED_STAGES = [('audio_extract', 'ingest'), ('audio_clean', 'audio_extract'), ('audio_events', 'audio_clean'), ('thumb_overlay', 'thumb_best'), ('sun', 'places'), ('palette', 'proxy')]


def load(name):
    p = os.path.join(race_dir(name), 'race.json')
    if not os.path.exists(p): raise FileNotFoundError(f'no race {name!r}: run `strata360 init {name} --library PATH` first ({p})')
    cfg = copy.deepcopy(DEFAULTS)
    for k, v in json.load(open(p)).items():
        cfg[k] = {**cfg[k], **v} if isinstance(v, dict) and isinstance(cfg.get(k), dict) else v
    if is_project_path(name) and not (cfg.get('library') and os.path.isdir(cfg['library'])): cfg['library'] = os.path.abspath(str(name))          # a project made on another computer (/Volumes/Expansion/...): its footage is the folder it sits in
    for new, after in ADDED_STAGES:                                                       # stages added after a project was made join it, right after the one they follow
        if 'transcribe' in cfg['stages'] and new not in cfg['stages'] and after in cfg['stages']: cfg['stages'].insert(cfg['stages'].index(after) + 1, new)
    return cfg


def save(name, cfg):
    os.makedirs(race_dir(name), exist_ok=True)
    json.dump(cfg, open(os.path.join(race_dir(name), 'race.json'), 'w'), indent=2)
