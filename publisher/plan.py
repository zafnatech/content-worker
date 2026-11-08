"""Rules: which videos may enter the queue, and when each channel posts (daily caps + fixed slots)."""
import os
import json
import datetime
from zoneinfo import ZoneInfo

from . import store

HERE = store.HERE

# Starting points from the Nov 2026 research (docs/ESTRATEGIA-REDES.md): few, relevant hashtags per network.
MAX_TAGS = {'instagram': 4, 'facebook': 2, 'tiktok': 4, 'youtube': 2, 'linkedin': 3}
# TikTok has its own AI switch (video_made_with_ai); Meta/YouTube/LinkedIn get a plain line in the text.
DISCLOSE_IN_CAPTION = {'instagram', 'facebook', 'youtube', 'linkedin'}


def load_channels():
    p = os.environ.get('CHANNELS_FILE') or os.path.join(HERE, 'channels.json')
    if not os.path.exists(p):
        raise SystemExit('Falta channels.json. Copia channels.example.json -> channels.json y pon los integration_id (python3 publish.py integrations).')
    with open(p, encoding='utf-8') as fh:
        return json.load(fh)


def utc_iso(dt):
    return dt.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:00.000Z')


def next_slot(ch, tz, now, lead_min=15):
    cap, slots = int(ch.get('daily_cap', 2)), sorted(ch.get('slots') or ['12:30', '19:00'])
    taken = store.rows('channel=? AND scheduled_at IS NOT NULL AND status IN ("queued","sent")', (ch['key'],))
    taken_iso = {r['scheduled_at'] for r in taken}
    per_day = {}
    for r in taken:
        d = datetime.datetime.strptime(r['scheduled_at'][:16], '%Y-%m-%dT%H:%M').replace(tzinfo=datetime.timezone.utc).astimezone(tz).date()
        per_day[d] = per_day.get(d, 0) + 1
    day0 = now.astimezone(tz).date()
    for i in range(60):
        day = day0 + datetime.timedelta(days=i)
        if per_day.get(day, 0) >= cap:
            continue
        for s in slots:
            h, m = map(int, s.split(':'))
            t = datetime.datetime(day.year, day.month, day.day, h, m, tzinfo=tz)
            if t < now + datetime.timedelta(minutes=lead_min) or utc_iso(t) in taken_iso:
                continue
            return t
    raise RuntimeError(f'Sin horario libre en 60 días para {ch["key"]}')


def assign(row_ids_by_channel, cfg, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    tz = ZoneInfo(cfg.get('timezone', 'America/New_York'))
    chans = {c['key']: c for c in cfg['channels']}
    for rid, key in row_ids_by_channel:
        t = next_slot(chans[key], tz, now)
        store.update(rid, scheduled_at=utc_iso(t), status='queued')


def enqueue(manifest_path, cfg):
    """Returns (ok, message). Refuses drafts, silent videos and files that do not exist."""
    with open(manifest_path, encoding='utf-8') as fh:
        m = json.load(fh)
    vid = m.get('id', '?')
    if m.get('draft'):
        return False, f'{vid}: es BORRADOR, no se publica'
    if 'PENDIENTE' in str(m.get('voice', '')):
        return False, f'{vid}: tiene escenas sin voz'
    f = m.get('file', '')
    f = f if os.path.isabs(f) else os.path.join(HERE, f)
    if not os.path.exists(f):
        return False, f'{vid}: no encuentro {f}'
    chans = [c for c in cfg['channels'] if c.get('enabled') and c.get('brand') == m.get('brand') and c.get('integration_id')]
    if not chans:
        return False, f'{vid}: no hay canales activos de la marca {m.get("brand")} en channels.json'
    base = m.get('caption', '').strip()
    tags = ['#' + h.lstrip('#') for h in (m.get('hashtags') or [])]
    per_net = m.get('captions') or {}      # optional per-network text written by hand: {"instagram": "...", "tiktok": "..."}
    titles = m.get('titles') or {}         # optional per-network title (YouTube)
    disclosure = (cfg.get('ai_disclosure_line') or '').strip() if m.get('ai_disclosure', True) else ''

    def caption_for(net):
        if per_net.get(net):               # hand-written text is used as is (the author controls its hashtags)
            text = per_net[net].strip()
        else:
            text = base
            if tags:
                text += '\n\n' + ' '.join(tags[:MAX_TAGS.get(net, 3)])
        if disclosure and net in DISCLOSE_IN_CAPTION and disclosure not in text:
            text += '\n\n' + disclosure
        return text

    verify = m.get('verify_before_publish') or []
    review = cfg.get('approval', 'if_verify') == 'always' or (cfg.get('approval', 'if_verify') == 'if_verify' and verify)
    status = 'needs_review' if review else 'pending_slot'
    new = []
    for c in chans:
        if store.insert(vid, c['key'], f, titles.get(c['network']) or m.get('title') or vid, caption_for(c['network']), status, verify):
            new.append(c['key'])
    if not new:
        return False, f'{vid}: ya estaba en la cola'
    if not review:
        assign([(r['id'], r['channel']) for r in store.rows('video_id=? AND status="pending_slot"', (vid,))], cfg)
    return True, f'{vid}: {len(new)} canal(es), ' + ('espera tu aprobación' if review else 'programado')


def approve(video_id, cfg, now=False):
    """now=True: schedule every channel a few minutes from now (first-slot rules ignored); else next free slot."""
    rows = store.rows('video_id=? AND status IN ("needs_review","failed","skipped")', (video_id,))
    if now:
        t = utc_iso(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=3))
        for r in rows:
            store.update(r['id'], scheduled_at=t, status='queued')
        return len(rows)
    assign([(r['id'], r['channel']) for r in rows], cfg)
    return len(rows)
