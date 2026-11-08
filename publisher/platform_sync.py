"""Registers finished videos in the DiniDine/Zafnatech platform (panel "Contenido") so they can be approved from the iPad.

  python3 publish.py sync [--dry]          # upload new videos to Cloudinary + register them (nothing is published here)
  python3 publish.py platform-channels-sql # SQL to seed the platform's channel list from channels.json (run once, with OK)

Env in .env (never in chat or git):
  CLOUDINARY_CLOUD_NAME, CLOUDINARY_UPLOAD_PRESET   (an UNSIGNED upload preset: no secret lives on this computer)
  CONTENT_INGEST_URL (https://<platform>/api/content/ingest), CONTENT_INGEST_TOKEN
Does not use publish.db. A video synced here is skipped by `enqueue-new`, so it is never published twice.
Stdlib only.
"""
import os
import re
import json
import uuid
import hashlib
import datetime
import mimetypes
import urllib.request
import urllib.error
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.environ.get('PLATFORM_SYNC_STATE') or os.path.join(HERE, 'out', '.platform-sync.json')
MAX_VIDEO_BYTES = 100 * 1024 * 1024  # Cloudinary Free: 100 MB per video


class SyncError(Exception):
    pass


def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding='utf-8') as fh:
            return json.load(fh)
    return {'videos': {}, 'slots': {}}


def save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def synced_ids():
    return set(load_state().get('videos', {}))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _utc_iso(dt):
    return dt.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:00Z')


def next_slot(ch, tz, now, taken, lead_min=15):
    """Next free slot of a channel: respects daily_cap and the fixed slots; `taken` = ISO UTC strings already planned."""
    cap, slots = int(ch.get('daily_cap', 1)), sorted(ch.get('slots') or ['12:00'])
    per_day = {}
    for iso in taken:
        d = datetime.datetime.strptime(iso[:16], '%Y-%m-%dT%H:%M').replace(tzinfo=datetime.timezone.utc).astimezone(tz).date()
        per_day[d] = per_day.get(d, 0) + 1
    day0 = now.astimezone(tz).date()
    for i in range(60):
        day = day0 + datetime.timedelta(days=i)
        if per_day.get(day, 0) >= cap:
            continue
        for s in slots:
            h, m = map(int, s.split(':'))
            t = datetime.datetime(day.year, day.month, day.day, h, m, tzinfo=tz)
            if t < now + datetime.timedelta(minutes=lead_min) or _utc_iso(t) in taken:
                continue
            return t
    raise SyncError(f'Sin horario libre en 60 días para {ch["key"]}')


def _multipart(fields, file_field, filename, data):
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    ctype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
                  f'Content-Type: {ctype}\r\n\r\n').encode() + data + b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    return b''.join(parts), f'multipart/form-data; boundary={boundary}'


def _post(url, body, headers, timeout=600):
    req = urllib.request.Request(url, data=body, method='POST', headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()[:300].decode('utf-8', 'replace')
        try:
            msg = json.loads(raw).get('error') or raw
        except Exception:
            msg = raw
        raise SyncError(f'{e.code}: {msg}')
    except urllib.error.URLError as e:
        raise SyncError(f'inalcanzable: {e.reason}')


def upload_cloudinary(path, public_id):
    cloud, preset = os.environ.get('CLOUDINARY_CLOUD_NAME'), os.environ.get('CLOUDINARY_UPLOAD_PRESET')
    if not (cloud and preset):
        raise SyncError('Faltan CLOUDINARY_CLOUD_NAME y CLOUDINARY_UPLOAD_PRESET en .env')
    base = os.environ.get('CLOUDINARY_API_BASE') or 'https://api.cloudinary.com'
    with open(path, 'rb') as fh:
        data = fh.read()
    body, ctype = _multipart({'upload_preset': preset, 'public_id': public_id}, 'file', os.path.basename(path), data)
    _, out = _post(f'{base}/v1_1/{cloud}/video/upload', body, {'Content-Type': ctype})
    if not out.get('public_id'):
        raise SyncError('Cloudinary no devolvió public_id')
    return out['public_id']


def ingest(payload):
    url, token = os.environ.get('CONTENT_INGEST_URL'), os.environ.get('CONTENT_INGEST_TOKEN')
    if not (url and token):
        raise SyncError('Faltan CONTENT_INGEST_URL y CONTENT_INGEST_TOKEN en .env')
    _, out = _post(url, json.dumps(payload).encode(), {'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'}, 60)
    return out['video_id']


def build_payload(m, media_key, asset_hash, cfg, state, now):
    """Payload for POST /api/content/ingest. Captions/titles per network only when written by hand in the job."""
    tz = ZoneInfo(cfg.get('timezone', 'America/New_York'))
    per_net, titles = m.get('captions') or {}, m.get('titles') or {}
    chans = [c for c in cfg['channels'] if c.get('enabled') and c.get('brand') == m.get('brand') and c.get('integration_id')]
    if not chans:
        raise SyncError(f'{m.get("id")}: no hay canales activos de la marca {m.get("brand")}')
    pubs = []
    for c in chans:
        taken = state['slots'].setdefault(c['key'], [])
        when = _utc_iso(next_slot(c, tz, now, taken))
        taken.append(when)
        pub = {'channel_key': c['key'], 'scheduled_at': when}
        if titles.get(c['network']):
            pub['title'] = titles[c['network']]
        if per_net.get(c['network']):
            pub['caption'] = per_net[c['network']].strip()
        pubs.append(pub)
    payload = {
        'brand': m['brand'], 'job_key': m['id'], 'title': m.get('title') or m['id'],
        'caption': (m.get('caption') or '').strip(), 'hashtags': [h.lstrip('#') for h in (m.get('hashtags') or [])],
        'duration_s': m.get('duration_s'), 'media_key': media_key,
        'voice_chars': m.get('voice_chars'), 'voice_cost_usd': m.get('voice_cost_usd_est'),
        'verify_notes': [str(x)[:300] for x in (m.get('verify_before_publish') or [])][:20],
        'source': 'factory', 'publications': pubs,
    }
    lineage = {'asset_hash': asset_hash}
    lin = m.get('lineage') or {}   # {"parent_job": "<job id already synced>", "change_kind": "new_piece", "substantive_change": "..."}
    if lin.get('parent_job'):
        parent = state['videos'].get(lin['parent_job'])
        if not parent:
            raise SyncError(f'{m["id"]}: el video padre "{lin["parent_job"]}" aún no está sincronizado')
        lineage['parent_video_id'] = parent['platform_video_id']
        lineage['change_kind'] = lin.get('change_kind', 'new_piece')
        lineage['substantive_change'] = lin.get('substantive_change', '')
    payload['lineage'] = lineage
    return payload


def eligible(m, path):
    """(ok, reason). Same gate as the local queue: no drafts, no silent videos, file must exist, Cloudinary Free size cap."""
    vid = m.get('id', '?')
    if m.get('draft'):
        return False, f'{vid}: es BORRADOR'
    if 'PENDIENTE' in str(m.get('voice', '')):
        return False, f'{vid}: tiene escenas sin voz'
    f = m.get('file', '')
    f = f if os.path.isabs(f) else os.path.join(HERE, f)
    if not os.path.exists(f):
        return False, f'{vid}: no encuentro {f}'
    if os.path.getsize(f) > MAX_VIDEO_BYTES:
        return False, f'{vid}: pesa más de 100 MB (límite de Cloudinary Free)'
    return True, f


def public_id_for(m, now):
    brand = re.sub(r'[^a-z0-9-]', '', str(m.get('brand', 'sin-marca')).lower()) or 'sin-marca'
    return f'zafnatech/{brand}/contenido/{now.strftime("%Y-%m")}/{m["id"]}'


def sync_new(cfg, manifests, dry=False, now=None, log=print):
    """manifests: list of (path, dict). Returns number registered. A failure on one video does not stop the others."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    state, done = load_state(), 0
    for path, m in manifests:
        vid = m.get('id')
        if not isinstance(m, dict) or 'file' not in m or 'brand' not in m or vid in state['videos']:
            continue
        ok, info = eligible(m, path)
        if not ok:
            log('- ' + info)
            continue
        try:
            asset_hash = sha256_file(info)
            public_id = public_id_for(m, now)
            if dry:
                payload = build_payload(m, public_id, asset_hash, cfg, json.loads(json.dumps(state)), now)
                log(json.dumps(payload, ensure_ascii=False, indent=1))
                continue
            media_key = upload_cloudinary(info, public_id)
            payload = build_payload(m, media_key, asset_hash, cfg, state, now)
            platform_id = ingest(payload)
            state['videos'][vid] = {'platform_video_id': platform_id, 'media_key': media_key,
                                    'synced_at': now.strftime('%Y-%m-%dT%H:%M:%SZ')}
            save_state(state)
            done += 1
            log(f'+ {vid}: registrado en el panel ({len(payload["publications"])} canal(es)), espera tu aprobación')
        except Exception as e:
            state = load_state()  # drop the slots reserved for this failed video
            log(f'x {vid}: {e}')
    return done


def channels_sql(cfg, brand_slug='dinidine'):
    """INSERTs to seed content_channels from channels.json (integration ids are not secrets). Review before running."""
    def q(s):
        return "'" + str(s).replace("'", "''") + "'"
    rows = []
    for c in cfg['channels']:
        if c.get('brand') != brand_slug:
            continue
        settings = dict(c.get('settings') or {})
        if cfg.get('ai_disclosure_line'):
            settings['ai_disclosure_line'] = cfg['ai_disclosure_line']
        slots = 'array[' + ', '.join(q(x) for x in (c.get('slots') or [])) + ']::text[]'
        name = c.get('display_name') or f"{brand_slug} {c['network']}"
        rows.append(f"((select id from public.brands where slug = {q(brand_slug)}), {q(c['key'])}, {q(c['network'])}, {q(name)}, "
                    f"{q(c['integration_id'])}, {str(bool(c.get('enabled'))).lower()}, {int(c.get('daily_cap', 1))}, "
                    f"{slots}, {q(json.dumps(settings, ensure_ascii=False))}::jsonb)")
    return ('-- Review first. Columns follow public.content_channels (docs/CONTENT_STUDIO.md).\n'
            'insert into public.content_channels (brand_id, key, network, display_name, integration_id, enabled, daily_cap, slots, settings) values\n'
            + ',\n'.join(rows) + '\non conflict (brand_id, key) do update set integration_id = excluded.integration_id, '
            'display_name = excluded.display_name, enabled = excluded.enabled, daily_cap = excluded.daily_cap, slots = excluded.slots, settings = excluded.settings;')
