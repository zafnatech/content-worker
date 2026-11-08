#!/usr/bin/env python3
"""Cloud worker: menu -> video -> voice -> Cloudinary -> panel "Contenido" (needs review). It NEVER publishes:
the kill switch and the approval live in the platform.

  python3 worker.py make --client maya [--kind top3|estrella] [--date 2026-11-08] [--dry]
  python3 worker.py run                      # one video for every client in WORKER_CLIENTS (daily cron on Render)

Env (host dashboard only, never git/chat):
  DINIDINE_API_URL, DINIDINE_API_KEY        read-only menu key (scope menu:read)
  ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID   (+ optional ELEVENLABS_MODEL_ID)
  CLOUDINARY_CLOUD_NAME, CLOUDINARY_UPLOAD_PRESET
  CONTENT_INGEST_URL, CONTENT_INGEST_TOKEN
  CHANNELS_JSON   {"timezone":"America/New_York","channels":[{key,network,brand,integration_id,enabled,daily_cap,slots}]}
  CLIENTS_JSON    {"maya":{"video_consent":true,"consent_date":"2026-11-01"}}   (restaurants that allowed video)
  WORKER_CLIENTS  comma list of client slugs;  WORKER_BRAND (default dinidine);  WORKER_VOICE_USD_CAP (default 1.00 per run)
Known limit (next platform change): slot state lives in out/.platform-sync.json, which is lost between cloud runs.
"""
import os
import sys
import json
import glob
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

from cf.env import load_env  # noqa: E402
load_env()
from cf import menu_video, guardrails  # noqa: E402


def log(msg):
    print(msg, flush=True)


def fetch_menu(client):
    from connectors import platform
    try:
        return platform.get(f'/businesses/{client}/menu')
    except SystemExit as e:
        raise RuntimeError(str(e))


def render_job(job, out_dir):
    import factory
    os.makedirs('jobs/_worker', exist_ok=True)
    path = os.path.join('jobs', '_worker', job['id'] + '.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(job, f, ensure_ascii=False, indent=1)
    hits = guardrails.check(job)
    if hits:
        raise RuntimeError('bloqueado por las reglas de la marca: ' + ', '.join(hits))
    code = factory.run(path, out_dir=out_dir)
    manifest = os.path.join(out_dir, job['id'] + '.json')
    if code != 0 or not os.path.exists(manifest):
        raise RuntimeError(f'render terminó con código {code}')
    with open(manifest, encoding='utf-8') as f:
        return manifest, json.load(f)


def sync(cfg, manifests, dry):
    from publisher import platform_sync
    return platform_sync.sync_new(cfg, manifests, dry=dry, log=log)


def load_channels():
    raw = os.environ.get('CHANNELS_JSON')
    if raw:
        return json.loads(raw)
    if os.path.exists('channels.json'):
        with open('channels.json', encoding='utf-8') as f:
            return json.load(f)
    raise RuntimeError('Falta CHANNELS_JSON (o channels.json)')


def make_one(client, kind, seed, brand='dinidine', dry=False, deps=None):
    """Returns ('ok'|'skip'|'error', message, voice_usd_est)."""
    d = {'menu': fetch_menu, 'render': render_job, 'sync': sync, 'channels': load_channels}
    d.update(deps or {})
    try:
        payload = d['menu'](client)
    except Exception as e:
        return 'error', f'{client}: no pude leer el menú ({e})', 0.0
    job = menu_video.build_job(payload, seed, kind, brand=brand, client=client)
    if job is None:
        return 'skip', f'{client}: el menú tiene muy pocos platos con precio para "{kind}"', 0.0
    out_dir = os.path.join('out', seed)
    try:
        manifest_path, m = d['render'](job, out_dir)
    except Exception as e:
        return 'error', f'{client}: {e}', 0.0
    cost = float(m.get('voice_cost_usd_est') or 0)
    if m.get('draft') or 'PENDIENTE' in str(m.get('voice', '')):
        return 'skip', f'{client}: sin permiso de video o sin voz; no se registra ({m.get("consent")})', cost
    try:
        done = d['sync'](d['channels'](), [(manifest_path, m)], dry)
    except Exception as e:
        return 'error', f'{client}: no pude registrar en el panel ({e})', cost
    return ('ok', f'{client}: {job["id"]} listo para tu aprobación', cost) if (done or dry) else (
        'skip', f'{client}: {job["id"]} ya estaba registrado', cost)


def run_all(seed=None, deps=None, dry=False):
    seed = seed or datetime.date.today().isoformat()
    brand = os.environ.get('WORKER_BRAND', 'dinidine')
    clients = [c.strip() for c in os.environ.get('WORKER_CLIENTS', '').split(',') if c.strip()]
    if not clients:
        log('WORKER_CLIENTS está vacío: no hay nada que hacer.')
        return 0
    cap = float(os.environ.get('WORKER_VOICE_USD_CAP', '1.00'))
    kinds, spent, errors = menu_video.KINDS, 0.0, 0
    for i, c in enumerate(clients):
        if spent >= cap:
            log(f'Tope de voz por corrida alcanzado (US$ {spent:.2f} de {cap:.2f}); el resto sigue mañana.')
            break
        kind = kinds[(datetime.date.fromisoformat(seed).toordinal() + i) % len(kinds)]
        status, msg, cost = make_one(c, kind, seed, brand, dry, deps)
        spent += cost
        errors += status == 'error'
        log(f'[{status}] {msg}')
    log(f'Voz estimada de esta corrida: US$ {spent:.2f}')
    return 1 if errors else 0


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    mk = sub.add_parser('make')
    mk.add_argument('--client', required=True)
    mk.add_argument('--kind', default='top3', choices=menu_video.KINDS)
    mk.add_argument('--date', default=datetime.date.today().isoformat())
    mk.add_argument('--dry', action='store_true')
    rn = sub.add_parser('run')
    rn.add_argument('--date')
    rn.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    if a.cmd == 'make':
        st, msg, _ = make_one(a.client, a.kind, a.date, os.environ.get('WORKER_BRAND', 'dinidine'), a.dry)
        log(f'[{st}] {msg}')
        sys.exit(1 if st == 'error' else 0)
    sys.exit(run_all(a.date, dry=a.dry))
