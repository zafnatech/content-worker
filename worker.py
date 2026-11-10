#!/usr/bin/env python3
"""Cloud worker: menu -> video -> voice -> Cloudinary -> panel "Contenido" (needs review). It NEVER publishes:
the kill switch and the approval live in the platform.

  python3 worker.py make --client maya [--kind top3|estrella] [--date 2026-11-08] [--dry]
  python3 worker.py run                      # the week ahead from brands/<brand>/grid.json (weekly cron on Render);
                                             # WORKER_MODE=legacy goes back to "a menu video per client per run"
  python3 worker.py plan [--date D] [--days N]   # prints the calendar (no render, no cost)
  python3 worker.py auto [--now ISO] [--dry]     # HOURLY cron: renders queue/*.json jobs whose time window is open right now
                                                 # (cf/autoq.py) and, only if brands/<brand>/auto.json has weekly=true, the old
                                                 # Saturday 11:00 UTC week plan. Nothing due = exits in a second, no network.

Env (host dashboard only, never git/chat):
  DINIDINE_API_URL, DINIDINE_API_KEY        read-only menu key (scope menu:read)
  ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID   (+ optional ELEVENLABS_MODEL_ID)
  CLOUDINARY_CLOUD_NAME, CLOUDINARY_UPLOAD_PRESET
  CONTENT_INGEST_URL, CONTENT_INGEST_TOKEN
  CHANNELS_JSON   {"timezone":"America/New_York","channels":[{key,network,brand,integration_id,enabled,daily_cap,slots}]}
  CLIENTS_JSON    only if WORKER_REQUIRE_CONSENT=1 (default 0: no restaurant permission needed, Jonathan's decision 8 Nov)
  WORKER_CLIENTS  `all` = every published restaurant of the brand (rotating, WORKER_MAX_PER_RUN per run, default 3), or a comma list of slugs;  WORKER_BRAND (default dinidine);  WORKER_VOICE_USD_CAP (default 1.00 per run)
The grid fixes every post time from the date (job.schedule), so no slot state has to survive between cloud runs.
  WORKER_BANK_APPROVED=1 approves the whole script bank (brands/<brand>/scripts.json) · WORKER_UNLOCK=tv,agents opens gated pieces
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
from cf import menu_video, guardrails, grid as gridmod, scripts as scriptmod, autoq, clipvideo  # noqa: E402


def log(msg):
    print(msg, flush=True)


def fetch_menu(client):
    from connectors import platform
    try:
        return platform.get(f'/businesses/{client}/menu')
    except SystemExit as e:
        raise RuntimeError(str(e))


def list_clients():
    """Slugs of every published business of the brand behind the API key (WORKER_CLIENTS=all)."""
    from connectors import platform
    try:
        data = platform.get('/businesses')
    except SystemExit as e:
        raise RuntimeError(str(e))
    return sorted(b['slug'] for b in data.get('businesses', []) if b.get('published') and b.get('slug'))


def render_job(job, out_dir):
    """Renders in a child process: its memory (~300 MB per video) is freed after every video, so three in a row
    never pile up (the 512 MB Render plan ran out of memory when it rendered in-process)."""
    import subprocess
    os.makedirs('jobs/_worker', exist_ok=True)
    path = os.path.join('jobs', '_worker', job['id'] + '.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(job, f, ensure_ascii=False, indent=1)
    hits = guardrails.check(job)
    if hits:
        raise RuntimeError('bloqueado por las reglas de la marca: ' + ', '.join(hits))
    proc = subprocess.run([sys.executable, 'factory.py', path, '--out-dir', out_dir], capture_output=True, text=True)
    for line in (proc.stdout or '').strip().splitlines()[-6:]:
        log('  ' + line)
    manifest = os.path.join(out_dir, job['id'] + '.json')
    if proc.returncode != 0 or not os.path.exists(manifest):
        err = (proc.stderr or '').strip().splitlines()[-1:] or ['']
        raise RuntimeError(f'render terminó con código {proc.returncode} {err[0][:160]}')
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


def make_one(client, kind, seed, brand='dinidine', dry=False, deps=None, schedule=None):
    """Returns ('ok'|'skip'|'error', message, voice_usd_est)."""
    d = {'menu': fetch_menu, 'render': render_job, 'sync': sync, 'channels': load_channels}
    d.update(deps or {})
    try:
        payload = d['menu'](client)
    except Exception as e:
        return 'error', f'{client}: no pude leer el menú ({e})', 0.0
    job = menu_video.build_job(payload, seed, kind, brand=brand, client=client,
                               require_consent=os.environ.get('WORKER_REQUIRE_CONSENT', '0') == '1')
    if job is None:
        return 'skip', f'{client}: el menú tiene muy pocos platos con precio para "{kind}"', 0.0
    job['schedule'] = schedule
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


def finish(label, job, deps, dry):
    """Render + register one prepared job. Returns (status, message, voice_usd_est)."""
    d = {'render': render_job, 'sync': sync, 'channels': load_channels}
    d.update(deps or {})
    out_dir = os.path.join('out', job['id'])
    try:
        manifest_path, m = d['render'](job, out_dir)
    except Exception as e:
        return 'error', f'{label}: {e}', 0.0
    cost = float(m.get('voice_cost_usd_est') or 0)
    if m.get('draft') or 'PENDIENTE' in str(m.get('voice', '')):
        return 'skip', f'{label}: sin voz; no se registra', cost
    try:
        done = d['sync'](d['channels'](), [(manifest_path, m)], dry)
    except Exception as e:
        return 'error', f'{label}: no pude registrar en el panel ({e})', cost
    return ('ok', f'{label}: {job["id"]} listo para tu aprobación', cost) if (done or dry) else (
        'skip', f'{label}: {job["id"]} ya estaba registrado', cost)


def resolve_week(brand, start, days=7, networks=None, clients=None, now=None, min_lead_hours=6, gates=None):
    """The week as a list of items, no side effects. Each item:
    {date, kind: menu|script|empty, id, client, script, schedule{network: iso_utc}, note}"""
    g = gridmod.load_grid(brand)
    if not g:
        return []
    bank = scriptmod.load_bank(brand)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    limit = (now + datetime.timedelta(hours=min_lead_hours)).strftime('%Y-%m-%dT%H:%M:00Z')
    min_days = int(g.get('min_days', 75))
    items = []
    for day in gridmod.plan(g, start, days, networks):
        d = day['date']
        sched = {n: t for n, t in day['schedule'].items() if t >= limit}
        if not sched:
            continue
        it = {'date': d, 'kind': 'empty', 'id': None, 'client': None, 'script': None, 'schedule': sched, 'note': ''}
        if day['special']:
            s = scriptmod.by_id(bank, day['special'], gates)
            if s:
                it.update(kind='script', id=f'{s["id"]}-{d.isoformat()}', script=s)
            else:
                it['note'] = f'fecha especial «{day["special"]}» sin guion aprobado'
        else:
            notes = []
            for pillar in day['pillars']:
                if pillar == 'menu':
                    if not clients:
                        notes.append('menú: no hay restaurantes publicados')
                        continue
                    wk = gridmod.week_index(d)
                    client = clients[wk % len(clients)]
                    kind = menu_video.KINDS[(wk // len(clients)) % len(menu_video.KINDS)]
                    it.update(kind='menu', id=f'menu-{client}-{kind}-{d.isoformat()}', client=client, note=kind)
                    break
                pool = scriptmod.pool(bank, pillar, gates)
                i = gridmod.pick_index(d, len(pool), min_days)
                if i is None:
                    notes.append(f'{pillar}: sin guion disponible esta semana ({len(pool)} usables, ciclo de {gridmod.cycle_weeks(min_days)} semanas)')
                    continue
                s = pool[i]
                it.update(kind='script', id=f'{s["id"]}-{d.isoformat()}', script=s)
                break
            if it['kind'] == 'empty':
                it['note'] = '; '.join(notes)
        items.append(it)
    return items


def run_week(start=None, days=7, deps=None, dry=False):
    brand = os.environ.get('WORKER_BRAND', 'dinidine')
    d = dict(deps or {})
    start = start or (datetime.date.today() + datetime.timedelta(days=1))
    try:
        networks = {c['network'] for c in d.get('channels', load_channels)().get('channels', []) if c.get('enabled')}
    except Exception as e:
        log(f'[error] no pude leer los canales ({e})')
        return 1
    clients = []
    if os.environ.get('WORKER_CLIENTS', '').strip():
        raw = [c.strip() for c in os.environ['WORKER_CLIENTS'].split(',') if c.strip()]
        try:
            clients = d.get('list', list_clients)() if [c.lower() for c in raw] == ['all'] else raw
        except Exception as e:
            log(f'[aviso] no pude listar los restaurantes ({e}); esta semana sin video de menú')
    items = resolve_week(brand, start, days, networks, clients, now=d.get('now'), gates=d.get('gates'))
    log(f'Semana desde {start} · redes activas: {", ".join(sorted(networks)) or "ninguna"}')
    cap = float(os.environ.get('WORKER_VOICE_USD_CAP', '1.00'))
    spent, errors = 0.0, 0
    for it in items:
        day = it['date'].isoformat()
        if it['kind'] == 'empty':
            log(f'[skip] {day}: nada que publicar ({it["note"]})')
            continue
        if spent >= cap:
            log(f'Tope de voz alcanzado (US$ {spent:.2f} de {cap:.2f}); lo que falta se hace en la próxima corrida.')
            break
        if it['kind'] == 'menu':
            st, msg, cost = make_one(it['client'], it['note'], day, brand, dry, d, schedule=it['schedule'])
        else:
            job = scriptmod.build_job(it['script'], it['date'], brand, schedule=it['schedule'])
            st, msg, cost = finish(day, job, d, dry)
        spent += cost
        errors += st == 'error'
        log(f'[{st}] {day}: {msg}')
    log(f'Voz estimada de esta corrida: US$ {spent:.2f}')
    return 1 if errors else 0


def render_clip(job, out_dir):
    """Clip pieces render in-process: ffmpeg does the heavy work in its own process and Pillow only draws 4 PNGs."""
    try:
        return clipvideo.render(job, out_dir, date_ordinal=job.get('_ordinal'))
    except clipvideo.ClipError as e:
        raise RuntimeError(str(e))


def clip_schedule(job, brand, networks, now):
    """Explicit job['schedule'] {network: iso}, or post_date (+ optional times) resolved with the brand grid's times for that
    weekday. Past times are dropped; no usable time -> None (the platform then picks the next free slot)."""
    if isinstance(job.get('schedule'), dict) and job['schedule']:
        return job['schedule']
    if not job.get('post_date'):
        return None
    g = gridmod.load_grid(brand) or {}
    tz = g.get('timezone', 'America/New_York')
    d = datetime.date.fromisoformat(job['post_date'])
    times = dict(job.get('times') or {})
    if not times:
        wk = (g.get('weekly') or {}).get(gridmod.DAYS[d.weekday()]) or {}
        times = dict(wk.get('times') or g.get('special_times') or {})
    limit = (now + datetime.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:00Z')
    sched = {n: gridmod.to_utc_iso(d, t, tz) for n, t in times.items() if not networks or n in networks}
    return {n: t for n, t in sched.items() if t >= limit} or None


def run_auto(now=None, deps=None, dry=False, queue_dir=None):
    """Hourly entry point. Returns the process exit code (1 only when a job that was due failed)."""
    d = dict(deps or {})
    now = now or datetime.datetime.now(datetime.timezone.utc)
    brand = os.environ.get('WORKER_BRAND', 'dinidine')
    due, upcoming, missed, broken = autoq.split(autoq.load(queue_dir), now)
    for path, err in broken:
        log(f'[aviso] {os.path.basename(path)}: {err}')
    if missed:
        log(f'[aviso] {len(missed)} trabajo(s) de la cola cuya ventana ya pasó (no se ejecutan): ' + ', '.join(j['id'] for _, j in missed[-5:]))
    weekly = False
    try:
        with open(os.path.join(HERE, 'brands', brand, 'auto.json'), encoding='utf-8') as f:
            weekly = bool(json.load(f).get('weekly'))
    except (OSError, ValueError):
        pass
    weekly = weekly and now.weekday() == 5 and now.hour == 11
    if not due and not weekly:
        nxt = upcoming[0][1]['_start'].strftime('%Y-%m-%d %H:%MZ') if upcoming else 'ninguno'
        log(f'{now.strftime("%Y-%m-%d %H:%MZ")}: nada pendiente. Próximo trabajo en la cola: {nxt}.')
        return 0
    errors = 0
    if due:
        try:
            networks = {c['network'] for c in d.get('channels', load_channels)().get('channels', []) if c.get('enabled')}
        except Exception as e:
            log(f'[error] no pude leer los canales ({e})')
            return 1
        for path, job in due:
            job = {k: v for k, v in job.items() if not k.startswith('_')}
            job.setdefault('brand', brand)
            job['_ordinal'] = now.date().toordinal()
            job['schedule'] = clip_schedule(job, job['brand'], networks, now)
            deps2 = dict(d)
            deps2['render'] = d.get('render_clip', render_clip)
            st, msg, _ = finish(job['id'], job, deps2, dry)
            errors += st == 'error'
            log(f'[{st}] {msg}')
    if weekly:
        log('Sábado 11:00 UTC y weekly=true: planeo la semana.')
        errors += run_week(None, 7, d, dry) != 0
    return 1 if errors else 0


def show_plan(start, days, deps=None):
    brand = os.environ.get('WORKER_BRAND', 'dinidine')
    d = dict(deps or {})
    try:
        clients = d.get('list', list_clients)()
    except Exception as e:
        clients = []
        log(f'(sin lista de restaurantes: {e})')
    for it in resolve_week(brand, start, days, None, clients, now=d.get('now'), min_lead_hours=-24 * 365, gates=d.get('gates')):
        what = it['client'] + ' · ' + it['note'] if it['kind'] == 'menu' else (it['script']['id'] if it['script'] else '— ' + it['note'])
        nets = ', '.join(f'{n} {t[11:16]}Z' for n, t in sorted(it['schedule'].items()))
        log(f'{it["date"]} {it["kind"]:6} {what}   [{nets}]')


def run_all(seed=None, deps=None, dry=False):
    seed = seed or datetime.date.today().isoformat()
    brand = os.environ.get('WORKER_BRAND', 'dinidine')
    clients = [c.strip() for c in os.environ.get('WORKER_CLIENTS', '').split(',') if c.strip()]
    if not clients:
        log('WORKER_CLIENTS está vacío: no hay nada que hacer.')
        return 0
    day = datetime.date.fromisoformat(seed).toordinal()
    if [c.lower() for c in clients] == ['all']:
        try:
            clients = (deps or {}).get('list', list_clients)()
        except Exception as e:
            log(f'[error] no pude listar los restaurantes ({e})')
            return 1
        if not clients:
            log('No hay restaurantes publicados en la marca: nada que hacer.')
            return 0
        # Each run covers at most WORKER_MAX_PER_RUN restaurants; the window moves every day so all get a turn.
        mx = max(1, int(os.environ.get('WORKER_MAX_PER_RUN', '3')))
        start = (day * mx) % len(clients)
        clients = [clients[(start + i) % len(clients)] for i in range(min(mx, len(clients)))]
        log(f'Hoy toca: {", ".join(clients)}')
    cap = float(os.environ.get('WORKER_VOICE_USD_CAP', '1.00'))
    kinds, spent, errors = menu_video.KINDS, 0.0, 0
    for i, c in enumerate(clients):
        if spent >= cap:
            log(f'Tope de voz por corrida alcanzado (US$ {spent:.2f} de {cap:.2f}); el resto sigue mañana.')
            break
        kind = kinds[(day + i) % len(kinds)]
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
    au = sub.add_parser('auto')
    au.add_argument('--now', help='ISO UTC, for tests: 2026-11-10T05:00:00Z')
    au.add_argument('--dry', action='store_true')
    rn = sub.add_parser('run')
    rn.add_argument('--date')
    rn.add_argument('--dry', action='store_true')
    pl = sub.add_parser('plan')
    pl.add_argument('--date')
    pl.add_argument('--days', type=int, default=14)
    a = ap.parse_args()
    if a.cmd == 'make':
        st, msg, _ = make_one(a.client, a.kind, a.date, os.environ.get('WORKER_BRAND', 'dinidine'), a.dry)
        log(f'[{st}] {msg}')
        sys.exit(1 if st == 'error' else 0)
    if a.cmd == 'auto':
        sys.exit(run_auto(autoq.parse_ts(a.now) if a.now else None, dry=a.dry))
    if a.cmd == 'plan':
        show_plan(datetime.date.fromisoformat(a.date) if a.date else datetime.date.today(), a.days)
        sys.exit(0)
    brand = os.environ.get('WORKER_BRAND', 'dinidine')
    if os.environ.get('WORKER_MODE', 'grid') != 'legacy' and gridmod.load_grid(brand):
        sys.exit(run_week(datetime.date.fromisoformat(a.date) if a.date else None, dry=a.dry))
    sys.exit(run_all(a.date, dry=a.dry))
