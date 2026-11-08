"""Postiz Public API client (stdlib only). Format verified against docs.postiz.com (5 nov 2026).

Env (never in code or chat):
  POSTIZ_API_KEY   the API key from Postiz > Settings
  POSTIZ_API_URL   full base, WITH /public/v1:  cloud  https://api.postiz.com/public/v1
                                                self-host  https://<your-domain>/api/public/v1
Auth header is the raw key (no "Bearer"). Create-post is rate limited (90/hour self-hosted, 100 cloud), so one request
carries every channel that shares the same publish time.
"""
import os
import json
import uuid
import mimetypes
import urllib.request
import urllib.error


class PostizError(Exception):
    pass


def _cfg():
    key, base = os.environ.get('POSTIZ_API_KEY'), os.environ.get('POSTIZ_API_URL')
    if not (key and base):
        raise PostizError('Faltan POSTIZ_API_KEY y POSTIZ_API_URL en .env')
    return key, base.rstrip('/')


def _call(method, path, data=None, headers=None, timeout=300):
    key, base = _cfg()
    h = {'Authorization': key}
    h.update(headers or {})
    req = urllib.request.Request(base + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise PostizError(f'Postiz {e.code} en {path}: {e.read()[:300].decode("utf-8", "replace")}')
    except urllib.error.URLError as e:
        raise PostizError(f'Postiz inalcanzable: {e.reason}')


def integrations():
    """Connected channels (Postiz calls them integrations). Use the ids in channels.json."""
    return _call('GET', '/integrations')


def upload(path):
    """Multipart upload of a local video. Returns the media object {id, path, ...} to reference in posts."""
    boundary = uuid.uuid4().hex
    name = os.path.basename(path)
    ctype = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
            f'Content-Type: {ctype}\r\n\r\n').encode()
    with open(path, 'rb') as f:
        body = head + f.read() + f'\r\n--{boundary}--\r\n'.encode()
    return _call('POST', '/upload', body, {'Content-Type': f'multipart/form-data; boundary={boundary}'})


NETWORK_DEFAULTS = {
    'instagram': {'__type': 'instagram', 'post_type': 'post'},          # a single video published as post_type "post" is a Reel
    'facebook': {'__type': 'facebook'},
    'tiktok': {'__type': 'tiktok', 'privacy_level': 'SELF_ONLY', 'duet': False, 'stitch': False, 'comment': True,
               'autoAddMusic': 'no', 'brand_content_toggle': False, 'brand_organic_toggle': False,
               'video_made_with_ai': True, 'content_posting_method': 'DIRECT_POST'},
    'youtube': {'__type': 'youtube', 'type': 'private', 'selfDeclaredMadeForKids': 'no', 'tags': []},
}
TEXT_LIMIT = {'instagram': 2200, 'tiktok': 2200, 'facebook': 5000, 'youtube': 5000}


def settings_for(channel, title):
    """Network defaults + the channel's own overrides + the video title where the network wants one.
    Defaults are the SAFE ones: TikTok private and YouTube private until the platform apps are approved (see channels.example.json)."""
    net = channel['network']
    s = dict(NETWORK_DEFAULTS[net])
    s.update(channel.get('settings', {}))
    if net == 'youtube':
        s['title'] = (title or 'Video')[:100]
    if net == 'tiktok':
        s['title'] = (title or '')[:90]
    return s


def post_item(channel, media, caption, title):
    text = caption[:TEXT_LIMIT.get(channel['network'], 2200)]
    return {'integration': {'id': channel['integration_id']},
            'value': [{'content': text, 'image': [{'id': media['id'], 'path': media['path']}]}],
            'settings': settings_for(channel, title)}


def create(date_iso, items):
    """items: list of post_item(); one request, one publish time."""
    body = {'type': 'schedule', 'date': date_iso, 'shortLink': False, 'tags': [], 'posts': items}
    return _call('POST', '/posts', json.dumps(body).encode(), {'Content-Type': 'application/json'})
