#!/usr/bin/env python3
"""Cola de publicación automática (motor: Postiz). Cerebro propio: topes por cuenta, horarios, aprobación, nada sin voz ni borradores.

  python3 publish.py integrations        # lista tus cuentas conectadas en Postiz (para llenar channels.json)
  python3 publish.py enqueue-new         # mete a la cola los videos nuevos de out/*/*.json
  python3 publish.py approve <video-id>  # aprueba un video que esperaba revisión (o hazlo en el panel > Publicación)
  python3 publish.py sync [--dry]        # NUEVO: sube a Cloudinary y registra en el panel de la plataforma (aprobación en el iPad)
  python3 publish.py status
  python3 publish.py run [--dry]         # entrega a Postiz lo que toca en las próximas 48 h (--dry = solo muestra)
  python3 publish.py daemon              # enqueue-new + run cada 10 min (déjalo corriendo en el servidor)
Llaves en .env: POSTIZ_API_KEY, POSTIZ_API_URL. Nunca en el chat.
"""
import os
import sys
import glob
import json
import time
import argparse
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cf.env import load_env  # noqa: E402
load_env()
from publisher import store, plan, postiz, platform_sync  # noqa: E402


def cmd_enqueue_new(cfg):
    seen = {r['video_id'] for r in store.rows()} | platform_sync.synced_ids()  # synced to the platform = never queued here too
    for p in sorted(glob.glob(os.path.join(HERE, 'out', '*', '*.json'))):
        try:
            m = json.load(open(p, encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(m, dict) or 'file' not in m or 'brand' not in m or m.get('id') in seen:
            continue
        ok, msg = plan.enqueue(p, cfg)
        print(('+ ' if ok else '- ') + msg)


def cmd_run(cfg, dry=False, lookahead_h=48, max_requests=60):
    now = datetime.datetime.now(datetime.timezone.utc)
    limit = (now + datetime.timedelta(hours=lookahead_h)).strftime('%Y-%m-%dT%H:%M:%SZ')
    # A post whose time already passed (approved a while ago) goes out in ~2 minutes instead of failing.
    utc_iso = plan.utc_iso
    soon = utc_iso(now + datetime.timedelta(minutes=2))
    for r in store.rows('status="queued" AND scheduled_at < ?', (utc_iso(now + datetime.timedelta(minutes=1)),)):
        if not dry:
            store.update(r['id'], scheduled_at=soon)
    due = store.rows('status="queued" AND scheduled_at <= ?', (limit,))
    chans = {c['key']: c for c in cfg['channels']}
    groups = {}
    for r in due:
        groups.setdefault((r['video_id'], r['scheduled_at']), []).append(r)
    media, sent = {}, 0
    for (vid, when), rs in groups.items():
        if sent >= max_requests:
            print('Tope de peticiones por corrida; sigue en la próxima.')
            break
        try:
            if dry:
                m = {'id': 'DRY', 'path': 'https://example.invalid/' + os.path.basename(rs[0]['file'])}
            else:
                if rs[0]['file'] not in media:
                    media[rs[0]['file']] = postiz.upload(rs[0]['file'])
                m = media[rs[0]['file']]
            if dry:
                items = [postiz.post_item(chans[r['channel']], m, r['caption'], r['title']) for r in rs]
                print(json.dumps({'date': when, 'video': vid, 'posts': items}, ensure_ascii=False, indent=1))
                continue
            for r in rs:  # one request per channel: a failure on one network does not block the rest
                try:
                    item = postiz.post_item(chans[r['channel']], m, r['caption'], r['title'])
                    res = postiz.create(when, [item])
                    sent += 1
                    by_int = {x.get('integration'): x.get('postId') for x in (res if isinstance(res, list) else [])}
                    store.update(r['id'], status='sent', postiz_id=by_int.get(chans[r['channel']]['integration_id']), error=None)
                    print(f'✓ {vid} -> {r["channel"]} a las {when}')
                except Exception as e:
                    store.update(r['id'], status='failed', error=str(e)[:400])
                    print(f'✗ {vid} -> {r["channel"]}: {e}')
        except Exception as e:
            for r in rs:
                store.update(r['id'], status='failed', error=str(e)[:400])
            print(f'✗ {vid}: {e}')


def cmd_sync(cfg, dry=False):
    manifests = []
    for p in sorted(glob.glob(os.path.join(HERE, 'out', '*', '*.json'))):
        try:
            m = json.load(open(p, encoding='utf-8'))
        except Exception:
            continue
        if isinstance(m, dict):
            manifests.append((p, m))
    n = platform_sync.sync_new(cfg, manifests, dry=dry)
    print(f'{n} video(s) registrados en el panel' if not dry else 'Simulacro: no se subió ni registró nada.')


def cmd_status():
    for r in store.rows():
        print(f'{r["id"]:>3}  {r["status"]:<13} {r["channel"]:<18} {r["video_id"]:<32} {r["scheduled_at"] or "-"} {r["error"] or ""}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['integrations', 'enqueue-new', 'approve', 'skip', 'status', 'run', 'daemon', 'sync', 'platform-channels-sql'])
    ap.add_argument('arg', nargs='?')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--every', type=int, default=10)
    a = ap.parse_args()
    if a.cmd == 'integrations':
        print(json.dumps(postiz.integrations(), ensure_ascii=False, indent=1))
    elif a.cmd == 'status':
        cmd_status()
    else:
        cfg = plan.load_channels()
        if a.cmd == 'enqueue-new':
            cmd_enqueue_new(cfg)
        elif a.cmd == 'approve':
            print(f'{plan.approve(a.arg, cfg)} publicación(es) programadas')
        elif a.cmd == 'skip':
            for r in store.rows('video_id=? AND status IN ("needs_review","queued","pending_slot")', (a.arg,)):
                store.update(r['id'], status='skipped')
        elif a.cmd == 'sync':
            cmd_sync(cfg, a.dry)
        elif a.cmd == 'platform-channels-sql':
            print(platform_sync.channels_sql(cfg, a.arg or 'dinidine'))
        elif a.cmd == 'run':
            cmd_run(cfg, a.dry)
        elif a.cmd == 'daemon':
            while True:
                cmd_enqueue_new(cfg)
                cmd_run(cfg)
                time.sleep(a.every * 60)
