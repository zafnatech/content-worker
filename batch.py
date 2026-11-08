#!/usr/bin/env python3
"""Render many jobs:  python3 batch.py "jobs/*.json" [--workers 2] [--force] [--draft]

Skips jobs whose MP4 already exists today (use --force to redo). Writes out/<date>/manifest.csv with one row per
video: file, duration, voice status, consent status, caption. Blocked jobs (no client consent) are listed, not rendered."""
import os
import sys
import csv
import glob
import json
import argparse
import datetime
import subprocess
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cf.env import load_env  # noqa: E402
load_env()


def one(job, out_dir, draft):
    cmd = [sys.executable, os.path.join(HERE, 'factory.py'), job, '--out-dir', out_dir] + (['--draft'] if draft else [])
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
    return job, r.returncode, (r.stdout + r.stderr).strip().splitlines()[-1:] or ['']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pattern')
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--draft', action='store_true')
    a = ap.parse_args()
    out_dir = os.path.join(HERE, 'out', datetime.date.today().isoformat())
    os.makedirs(out_dir, exist_ok=True)
    jobs = sorted(glob.glob(os.path.join(HERE, a.pattern)))
    todo = []
    for j in jobs:
        jid = json.load(open(j, encoding='utf-8'))['id']
        if os.path.exists(os.path.join(out_dir, f'{jid}.mp4')) and not a.force:
            print(f'skip {jid} (ya existe)')
        else:
            todo.append(j)
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        results = list(ex.map(lambda j: one(j, out_dir, a.draft), todo))
    for j, code, last in results:
        print(('OK   ' if code == 0 else 'FALLO' if code != 3 else 'BLOQ ') + os.path.basename(j), '|', last[0] if last else '')
    rows = []
    for m in sorted(glob.glob(os.path.join(out_dir, '*.json'))):
        d = json.load(open(m, encoding='utf-8'))
        rows.append([d['id'], d['brand'], d['client'] or '', d['duration_s'], d['voice'], d['consent'], d['draft'], d['caption'], ' '.join(d['hashtags']), d['file']])
    with open(os.path.join(out_dir, 'manifest.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['id', 'marca', 'cliente', 'segundos', 'voz', 'permiso', 'borrador', 'caption', 'hashtags', 'archivo'])
        w.writerows(rows)
    print(f'manifest: {out_dir}/manifest.csv ({len(rows)} videos)')


if __name__ == '__main__':
    main()
