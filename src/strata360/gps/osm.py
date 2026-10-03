"""A shared, cached lookup service for OpenStreetMap data (the Overpass API), for anything that needs map facts: the places stage, road stretches along a track (gps/roads.py), future street-level work.

The public Overpass servers are free, shared and rate limited (HTTP 429/504/406, "runtime error" replies), and none of them has an API key. So requests are spread over a pool of mirrors in round robin:
a mirror is used at most once per `min_gap_s`, a mirror that fails or is told to slow down rests for a while (longer each time in a row, `COOLDOWN_S` up to `COOLDOWN_MAX_S`, and it is forgiven by its next success),
and a failed attempt moves on to the next mirror. Many threads may ask at once (`query_many`): each takes the next mirror that is ready, so n healthy mirrors give about n times the throughput.
Every good answer is kept on disk in `cache_dir` under a key (default: the query text), so a repeat, in this run or a later project, costs nothing; a failure is never cached.
The cache files are named like the places stage's (`sha1(key)[:20].json`), so `key=` lets that stage keep the answers it already has.
Dependencies on the outside world (`fetch`, `sleep`, `clock`) are arguments, so the whole thing is testable without a network."""
import hashlib, json, os, threading, time, urllib.parse, urllib.request

UA = 'strata360-personal-race-film/0.1 (local tool; map lookups along my own race track)'
MIRRORS = ['https://overpass-api.de/api/interpreter', 'https://lz4.overpass-api.de/api/interpreter', 'https://z.overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter',
           'https://overpass.private.coffee/api/interpreter', 'https://overpass.openstreetmap.fr/api/interpreter', 'https://maps.mail.ru/osm/tools/overpass/api/interpreter', 'https://overpass.osm.ch/api/interpreter']
MIN_GAP_S = 1.1                   # between two requests to the same mirror
COOLDOWN_S, COOLDOWN_MAX_S = 20.0, 600.0
DRIVABLE = ('motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'unclassified', 'residential', 'living_street', 'service')


def _fetch(url, data, timeout):
    req = urllib.request.Request(url, data=data, headers={'User-Agent': UA, 'Accept': '*/*'})
    return urllib.request.urlopen(req, timeout=timeout).read()


class Overpass:
    def __init__(self, cache_dir, mirrors=None, min_gap_s=MIN_GAP_S, fetch=_fetch, sleep=time.sleep, clock=time.time, timeout=120, tries=None):
        self.cache_dir, self.mirrors = cache_dir, list(mirrors or MIRRORS); self.min_gap_s, self._fetch, self._sleep, self._clock, self.timeout = min_gap_s, fetch, sleep, clock, timeout
        self.tries = tries or 3 * len(self.mirrors); self._lock = threading.Lock(); self._next = 0
        self._ready = {m: 0.0 for m in self.mirrors}; self._bad = {m: 0 for m in self.mirrors}; self.stats = {m: dict(ok=0, failed=0) for m in self.mirrors}; self.cached = 0
        os.makedirs(cache_dir, exist_ok=True)

    def _file(self, key): return os.path.join(self.cache_dir, hashlib.sha1(key.encode()).hexdigest()[:20] + '.json')

    def _take(self):
        """The next mirror that is ready (round robin), reserved for this caller, after waiting for one if none is ready yet."""
        while True:
            with self._lock:
                now = self._clock(); n = len(self.mirrors)
                for k in range(n):
                    m = self.mirrors[(self._next + k) % n]
                    if self._ready[m] <= now: self._next = (self._next + k + 1) % n; self._ready[m] = now + self.min_gap_s; return m, 0.0
                wait = min(self._ready.values()) - now
            self._sleep(max(0.05, wait))

    def _report(self, m, good):
        with self._lock:
            if good: self._bad[m] = 0; self.stats[m]['ok'] += 1
            else:
                self._bad[m] += 1; self.stats[m]['failed'] += 1; self._ready[m] = max(self._ready[m], self._clock() + min(COOLDOWN_MAX_S, COOLDOWN_S * 2 ** (self._bad[m] - 1)))

    def query(self, ql, key=None):
        """The parsed JSON answer to an Overpass QL query, from the disk cache or the next mirror; None when every try failed (nothing is cached then)."""
        cf = self._file(key or ql)
        if os.path.exists(cf):
            try:
                out = json.load(open(cf)); self.cached += 1; return out
            except ValueError: pass
        body = urllib.parse.urlencode({'data': ql}).encode()
        for _ in range(self.tries):
            m, _w = self._take()
            try:
                out = json.loads(self._fetch(m, body, self.timeout).decode())
                if not isinstance(out, dict) or 'elements' not in out or 'runtime error' in str(out.get('remark', '')): raise ValueError('mirror gave no usable answer')
            except Exception:
                self._report(m, False); continue
            self._report(m, True); tmp = cf + f'.{os.getpid()}.{threading.get_ident()}.tmp'; json.dump(out, open(tmp, 'w')); os.replace(tmp, cf); return out
        return None

    def query_many(self, queries, workers=None):
        """Answers for a list of queries (each a QL string or a (ql, key) pair) in the same order, asked in parallel across the mirrors; an entry is None where it could not be had."""
        from concurrent.futures import ThreadPoolExecutor
        qs = [q if isinstance(q, tuple) else (q, None) for q in queries]
        with ThreadPoolExecutor(workers or len(self.mirrors)) as ex: return list(ex.map(lambda q: self.query(*q), qs))


_pools = {}


def pool(cache_dir):
    """The one Overpass pool for a cache folder in this process, so every caller shares the mirrors' rest times."""
    if cache_dir not in _pools: _pools[cache_dir] = Overpass(cache_dir)
    return _pools[cache_dir]


def ways_ql(bbox, kinds=DRIVABLE):
    """The query for the ways tagged highway=<one of kinds> inside bbox (south, west, north, east), with their tags and geometry."""
    s, w, n, e = bbox; return f'[out:json][timeout:90];way["highway"~"^({"|".join(kinds)})$"]({s:.5f},{w:.5f},{n:.5f},{e:.5f});out tags geom;'


def ways(answer):
    """[{id, highway, name, geometry: [(lat, lon), ...]}] from an answer to a `ways_ql` query."""
    return [dict(id=x['id'], highway=x['tags'].get('highway'), name=x['tags'].get('name'), geometry=[(g['lat'], g['lon']) for g in x['geometry']]) for x in answer['elements'] if x.get('type') == 'way' and x.get('geometry')]
