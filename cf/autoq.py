"""Git-driven queue for the hourly `auto` run. Jobs live in queue/*.json; a job runs ONLY inside its time window:

    run_after <= now < run_after + window_min   (default 60 minutes)

With an hourly cron that is exactly one tick per job, so nothing has to remember what already ran (Render's disk is
ephemeral) and a job that is edited later never re-fires. A job whose window passed is reported once and left alone.
Use a :30 start (05:30Z) so the :00 tick lands in the middle of the window and tolerates a late/early scheduler.
The platform ignores a job_key it already has, so even a double run cannot create a second video.
"""
import os
import re
import json
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(ROOT, 'queue')
DEFAULT_WINDOW_MIN = 60


class QueueError(Exception):
    pass


def parse_ts(s):
    if not isinstance(s, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?Z', s):
        raise QueueError(f'run_after inválido: {s!r} (usa 2026-11-10T05:30:00Z)')
    s = s[:-1] + ('' if len(s) > 17 else ':00')
    return datetime.datetime.fromisoformat(s).replace(tzinfo=datetime.timezone.utc)


def load(queue_dir=None):
    """[(path, job, error)] sorted by run_after. A broken file is returned with its error instead of stopping the rest."""
    d = queue_dir or QUEUE
    out = []
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if not name.endswith('.json') or name.startswith('_') or name.startswith('.'):
            continue
        path = os.path.join(d, name)
        try:
            with open(path, encoding='utf-8') as f:
                job = json.load(f)
            if not isinstance(job, dict):
                raise QueueError('el archivo debe ser un objeto JSON')
            job['_start'] = parse_ts(job.get('run_after'))
            win = int(job.get('window_min', DEFAULT_WINDOW_MIN))
            if not 5 <= win <= 720:
                raise QueueError('window_min debe estar entre 5 y 720')
            job['_end'] = job['_start'] + datetime.timedelta(minutes=win)
            if job.get('type', 'clip') != 'clip':
                raise QueueError(f'tipo no soportado todavía: {job.get("type")}')
            out.append((path, job, None))
        except (QueueError, ValueError, OSError) as e:
            out.append((path, None, str(e)))
    return sorted(out, key=lambda x: (x[1] or {}).get('_start') or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))


def split(entries, now):
    """(due, upcoming, missed, broken). `missed` = window already closed (reported, never run)."""
    due, upcoming, missed, broken = [], [], [], []
    for path, job, err in entries:
        if err:
            broken.append((path, err))
        elif job['_start'] <= now < job['_end']:
            due.append((path, job))
        elif now < job['_start']:
            upcoming.append((path, job))
        else:
            missed.append((path, job))
    return due, upcoming, missed, broken
