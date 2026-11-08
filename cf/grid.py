"""Weekly content grid: which piece goes out which day, on which networks and at what time. Pure functions.

brands/<slug>/grid.json:
  {"timezone": "America/New_York", "min_days": 75,
   "weekly": {"mon": {"pillars": ["consejo"], "times": {"instagram": "12:00", ...}}, ...},
   "special": {"2026-11-25": "fecha-2026-11-25"}}

Why no state: the date decides everything. The same date always gives the same piece, id and time, so a rerun is idempotent
(the platform ignores a job_key it already has) and nothing has to survive between cloud runs.
The 75-day rule (a hypothesis of the project, not a network rule): a pillar has one slot a week, so a bank is walked on a
cycle of ceil(75/7) = 11 weeks; a bank with fewer than 11 pieces leaves some weeks empty instead of repeating early.
"""
import os
import json
import math
import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']


def load_grid(brand):
    path = os.path.join(ROOT, 'brands', brand, 'grid.json')
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def cycle_weeks(min_days=75):
    return math.ceil(min_days / 7)


def week_index(date):
    """Monday-based week number, stable across years."""
    return (date.toordinal() - 1) // 7


def pick_index(date, pool_len, min_days=75):
    """Position in a pool for this week, or None when the pool is too small to fill this week without repeating early."""
    if pool_len <= 0:
        return None
    n = max(pool_len, cycle_weeks(min_days))
    i = week_index(date) % n
    return i if i < pool_len else None


def to_utc_iso(date, hhmm, tz_name):
    h, m = map(int, hhmm.split(':'))
    t = datetime.datetime(date.year, date.month, date.day, h, m, tzinfo=ZoneInfo(tz_name))
    return t.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:00Z')


def plan(grid, start, days=7, networks=None):
    """[{date, pillars, special, schedule{network: iso_utc}}] for `days` days from `start`.
    `networks` limits to the enabled ones (None = all in the grid). Days with no times and no special are left out."""
    tz = grid.get('timezone', 'America/New_York')
    out = []
    for k in range(days):
        d = start + datetime.timedelta(days=k)
        wk = (grid.get('weekly') or {}).get(DAYS[d.weekday()]) or {}
        if d.isoformat() in (grid.get('skip') or []):
            continue
        special = (grid.get('special') or {}).get(d.isoformat())
        times = dict(wk.get('times') or {})
        if special and not times:
            times = dict((grid.get('special_times') or {}))
        if networks is not None:
            times = {n: t for n, t in times.items() if n in networks}
        if not times or not (wk.get('pillars') or special):
            continue
        out.append({'date': d, 'pillars': list(wk.get('pillars') or []), 'special': special,
                    'schedule': {n: to_utc_iso(d, t, tz) for n, t in times.items()}})
    return out
