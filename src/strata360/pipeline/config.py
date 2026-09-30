"""Race configuration: one `race.json` per race collection (races/<name>/race.json), merged over these defaults.

Every stage declares which config keys it depends on (stages.py), so changing a setting re-runs only the stages that use it."""
import copy, json, os

DEFAULTS = {
    'name': None,
    'library': None,                        # folder holding the camera files (searched recursively)
    'camera': 'dji_osmo_360',
    # The camera clock. `utc_offset_hours` is the camera clock's offset from UTC: 0 = the camera shows UTC (the default assumption, which
    # matched the one clip checked in M0), 1 = it shows Belgian winter local time recorded as if it were UTC. `verified` should be set to
    # true only after checking against the GPX or a known event; until then start times are reported as provisional.
    'camera_clock': {'utc_offset_hours': 0.0, 'verified': False, 'note': ''},
    'languages': ['en'],                    # languages the speech identifier may choose from (e.g. ['en', 'fr', 'nl', 'de'] in Belgium)
    'whisper_model': 'large-v3-turbo',
    'align_languages': ['en'],              # languages with a forced-alignment model (wordtimes.LANGUAGE_MODELS)
    'exposure_every_frames': 10,
    'people_every_frames': 50,
    'profile': 'me',
    'scenes_every_s': 5.0,
    'llm': {'provider': 'vertex', 'model': 'gemini-2.5-pro'},           # the voice-over script writer: Gemini Pro through a Google Cloud (Vertex AI) key in secrets.env; or 'gemini' (AI Studio key), 'anthropic', 'local' (mlx-lm)
    'places': {'radius_m': 1000},                 # OpenStreetMap lookups (README 18.4j); endpoints can be replaced by a self-hosted Nominatim / Overpass
    'proxy': {'size': '3840x1920', 'every_frames': 2, 'bitrate': '30M'},
    'stages': ['ingest', 'motion', 'proxy', 'thumb', 'places', 'preview', 'audio', 'transcribe', 'align', 'exposure', 'people', 'identity', 'scenes', 'speakers', 'candidates', 'thumb_best'],   # default set for `run` / `open`; `proxy` is opt-in (slow, large)
}


def races_root():
    return os.environ.get('STRATA_RACES', os.path.join(os.path.dirname(__file__), '..', '..', '..', 'races'))


PROJECT_SUBFOLDER = 'strata360'      # results live in <footage folder>/strata360/ (race.json, clips/, run.log, people/, ...); the GUI just asks for the footage folder


def is_project_path(name):
    return os.path.sep in str(name) or str(name).startswith('.') or os.path.isdir(os.path.join(str(name), PROJECT_SUBFOLDER))


def race_dir(name):
    """`name` is either a race name (races/<name>, the old layout) or a footage folder (any path): the results then live in <folder>/strata360/."""
    if is_project_path(name): return os.path.abspath(os.path.join(str(name), PROJECT_SUBFOLDER))
    return os.path.abspath(os.path.join(races_root(), name))


TRACK_NAMES = ('track.fit', 'track.gpx')      # the race track lives at <project>/track.fit or track.gpx (uploaded in the GUI or copied there)


def track_path(name, cfg=None):
    """The race track file of a project: the known filename in the project folder, else the (older) `gps` setting, else None."""
    for n in TRACK_NAMES:
        p = os.path.join(race_dir(name), n)
        if os.path.exists(p): return p
    g = (cfg or {}).get('gps')
    return g if g and os.path.exists(g) else None


def load(name):
    p = os.path.join(race_dir(name), 'race.json')
    if not os.path.exists(p): raise FileNotFoundError(f'no race {name!r}: run `strata360 init {name} --library PATH` first ({p})')
    cfg = copy.deepcopy(DEFAULTS)
    for k, v in json.load(open(p)).items():
        cfg[k] = {**cfg[k], **v} if isinstance(v, dict) and isinstance(cfg.get(k), dict) else v
    return cfg


def save(name, cfg):
    os.makedirs(race_dir(name), exist_ok=True)
    json.dump(cfg, open(os.path.join(race_dir(name), 'race.json'), 'w'), indent=2)
