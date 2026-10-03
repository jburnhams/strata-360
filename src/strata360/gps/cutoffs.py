"""Cut-off times for the checkpoints and the finish, typed in whatever form the race publishes them.

`parse(text, ctx)` works out what a typed cut-off means and returns {kind, elapsed_s}: `elapsed_s` is the cut-off as time since the start of the run and `kind` how it was read:

  since_start   a total time since the start of the race       "27h", "27:30", "1d 3h 30m", "total 27h30"
  since_last    a time since leaving the previous checkpoint     "6h", "5:30 from last", "leg 4h45" (the start for the first checkpoint)
  clock         a time of day, with a weekday or a date          "Sat 14:00", "2pm", "21/02 14:30", "sat 2:30pm"

Words say it outright (`from last`, `since last`, `leg`, `stage` for since_last; `total`, `from start` for since_start; a weekday, a date or am / pm for a clock time). Otherwise a bare "27h", "5:30" or "14:30" could be any of them, so every reading is worked out and the one
that fits is taken: later than the previous cut-off (they only get later), and of those the one nearest to when the run actually got there (a cut-off is set near the pace of the field), else the first. `ctx` carries: start (UTC seconds), tz, prev_ref_s (the
previous cut-off, or when the run reached the previous checkpoint, as time since the start), last_departure_s (time since the start when the run left the previous checkpoint), arrival_s (when it reached this one, or None)."""
import datetime as dt, re
from zoneinfo import ZoneInfo

DAYS = {'mon': 0, 'tue': 1, 'tues': 1, 'wed': 2, 'thu': 3, 'thur': 3, 'thurs': 3, 'fri': 4, 'sat': 5, 'sun': 6}
LAST_WORDS = r'(?:from|since|after)\s+(?:the\s+)?(?:last|previous|prev)(?:\s+(?:checkpoint|cp|aid(?:\s+station)?))?|\bleg\b|\bstage\b|\bsection\b'
START_WORDS = r'(?:from|since)\s+(?:the\s+)?start|\btotal\b|\boverall\b|\bgun\b'


def _unit_duration(s):
    """Seconds of a duration written with units ("2h30", "2h 30m", "1d 3h", "150 min", "2.5h"), or None when it is not one. A trailing bare number after h counts as minutes ("2h30")."""
    m = re.fullmatch(r'\s*(?:(\d+(?:[.,]\d+)?)\s*d(?:ays?)?)?\s*(?:(\d+(?:[.,]\d+)?)\s*(?:h(?:ours?|rs?)?|hrs?))?\s*(?:(\d+(?:[.,]\d+)?)\s*(?:m(?:in(?:ute)?s?)?)?)?\s*', s, re.I)
    if not m or not any(m.groups()): return None
    d, h, mi = (float(x.replace(',', '.')) if x else 0.0 for x in m.groups())
    if m.group(3) and not m.group(2) and not m.group(1) and not re.search(r'm', s, re.I): return None                    # a bare number is not a duration with units
    return d * 86400 + h * 3600 + mi * 60


def _colon_duration(s):
    """"27:30" or "27:30:15" as hours:minutes(:seconds); with a day part "1d 03:30"."""
    m = re.fullmatch(r'\s*(?:(\d+)\s*d\s*)?(\d{1,3}):(\d{2})(?::(\d{2}))?\s*', s, re.I)
    if not m: return None
    d, h, mi, sec = int(m.group(1) or 0), int(m.group(2)), int(m.group(3)), int(m.group(4) or 0)
    if mi >= 60 or sec >= 60: return None
    return d * 86400 + h * 3600 + mi * 60 + sec


def _time_of_day(s):
    """(hour, minute) from "14:30", "14h30", "1430", "2pm", "2:30 pm", or None."""
    m = re.fullmatch(r'\s*(\d{1,2})(?:[:h.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?\s*', s, re.I)
    if not m:
        m2 = re.fullmatch(r'\s*(\d{2})(\d{2})\s*', s)
        if not m2: return None
        h, mi, ap = int(m2.group(1)), int(m2.group(2)), None
    else: h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or '').lower().replace('.', '')
    if ap == 'pm' and h < 12: h += 12
    if ap == 'am' and h == 12: h = 0
    return (h, mi) if 0 <= h < 24 and 0 <= mi < 60 else None


def _clock_elapsed(day, date, hm, ctx, after_s):
    """Time since the start of a clock time: on weekday `day` (0 = Monday), or the date (month, day), or the next time of day after `after_s` when neither is given."""
    tz = ZoneInfo(ctx['tz']); t0 = dt.datetime.fromtimestamp(ctx['start'], dt.timezone.utc).astimezone(tz); h, mi = hm
    if date:
        mo, d = date; cand = dt.datetime(t0.year, mo, d, h, mi, tzinfo=tz)
        if cand < t0 - dt.timedelta(days=1): cand = cand.replace(year=t0.year + 1)
    elif day is not None:
        cand = dt.datetime.combine(t0.date(), dt.time(h, mi), tzinfo=tz); cand += dt.timedelta(days=(day - cand.weekday()) % 7)
        while (cand - t0).total_seconds() <= 0: cand += dt.timedelta(days=7)
    else:
        base = t0 + dt.timedelta(seconds=max(after_s, 0)); cand = dt.datetime.combine(base.date(), dt.time(h, mi), tzinfo=tz)
        while (cand - base).total_seconds() < 0: cand += dt.timedelta(days=1)
    return (cand - t0).total_seconds()


def parse(text, ctx):
    """See the module notes. Raises ValueError (with a message to show) when the text is not understood."""
    raw = (text or '').strip()
    if not raw: raise ValueError('empty')
    s = raw.lower(); kind_word = None
    if re.search(LAST_WORDS, s): kind_word = 'since_last'
    elif re.search(START_WORDS, s): kind_word = 'since_start'
    s = re.sub(LAST_WORDS + '|' + START_WORDS + r'|\bat\b|\bby\b|\bcut-?off\b|\bin\b', ' ', s); s = re.sub(r'\s+', ' ', s).strip()
    day = date = None
    m = re.search(r'\b(' + '|'.join(sorted(DAYS, key=len, reverse=True)) + r')[a-z]*\b', s)
    if m: day = DAYS[m.group(1)]; s = (s[:m.start()] + ' ' + s[m.end():]).strip()
    m = re.search(r'\b(\d{1,2})[/.-](\d{1,2})\b(?![:h])', s)
    if m and not re.search(r'\d{4}-\d{2}-\d{2}', s):
        a, b = int(m.group(1)), int(m.group(2)); date = (b, a) if b <= 12 and a <= 31 else None; s = (s[:m.start()] + ' ' + s[m.end():]).strip()
    elif (m := re.search(r'\b(\d{1,2})\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b', s)):
        date = ([x for x in ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')].index(m.group(2)) + 1, int(m.group(1))); s = (s[:m.start()] + ' ' + s[m.end():]).strip()
    s = s.strip(' ,;-')
    prev_ref, depart, arrival = ctx['prev_ref_s'], ctx['last_departure_s'], ctx.get('arrival_s')
    has_clock_words = day is not None or date is not None or bool(re.search(r'\b(am|pm|a\.m\.|p\.m\.)\b|\d(am|pm)', s))
    cands = []
    if has_clock_words:
        hm = _time_of_day(s) if s else (0, 0)
        if hm is None: raise ValueError(f'could not read the time of day in "{raw}"')
        cands.append(('clock', _clock_elapsed(day, date, hm, ctx, prev_ref)))
    else:
        dur = _unit_duration(s) if re.search(r'[dhm]', s) else None
        if dur is None: dur = _colon_duration(s)
        if dur is None and re.fullmatch(r'\d+(?:[.,]\d+)?', s): dur = float(s.replace(',', '.')) * 3600                     # a lone number is hours
        explicit_units = bool(re.search(r'[a-z]', s)) and not re.fullmatch(r'\d{1,2}[:.]\d{2}', s)
        if dur is not None:
            for k, base in (('since_start', 0.0), ('since_last', depart)): cands.append((k, base + dur))
        hm = None if (explicit_units or kind_word) else _time_of_day(s) if re.fullmatch(r'\d{1,2}[:.]\d{2}|\d{4}', s) else None
        if hm is not None: cands.append(('clock', _clock_elapsed(None, None, hm, ctx, prev_ref)))
    if not cands: raise ValueError(f'could not read "{raw}" as a time: try 27h, 5:30, "6h from last" or "Sat 14:00"')
    if kind_word:
        pick = [c for c in cands if c[0] == kind_word]
        if not pick: raise ValueError(f'"{raw}" cannot be a time {kind_word.replace("_", " ")}')
        cands = pick
    later = [c for c in cands if c[1] > prev_ref] or cands                                                                   # cut-offs only get later
    best = min(later, key=lambda c: abs(c[1] - arrival)) if arrival is not None and len(later) > 1 else later[0]
    return dict(kind=best[0], elapsed_s=round(best[1]))
