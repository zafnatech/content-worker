"""Menu -> video job. Pure functions: take what the platform's Agent API returns for a restaurant's menu
(GET /api/agent/v1/businesses/<slug>/menu) and build the job JSON that factory.py renders.

Rules baked in (Brand Book + project rules):
- Only real data from the menu. No invented figures, no testimonials, no promised results.
- Prices are shown on screen, never spoken (TTS mangles them).
- DiniDine does not announce native ordering: the video only shows the digital menu.
- Jonathan decided (8 Nov 2026) not to ask restaurants for permission: by default the job carries no `client`, so the
  clients.json consent gate does not apply. `require_consent=True` (env WORKER_REQUIRE_CONSENT=1) brings it back.
  Every video still waits for his approval in the panel, and a verify note reminds him whose name/prices it shows.
"""
import re
import hashlib
import unicodedata

KINDS = ('top3', 'estrella')


def slugify(text):
    t = unicodedata.normalize('NFKD', str(text)).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', t).strip('-')


def money(minor, currency='USD'):
    sym = {'USD': '$', 'EUR': '€', 'COP': '$'}.get(currency, '')
    v = minor / 100
    txt = f'{v:,.0f}' if v == int(v) else f'{v:,.2f}'
    return f'{sym}{txt}' if sym else f'{txt} {currency}'


def dish_price(d, currency='USD'):
    """"$12.50", or "desde $9" for dishes sold by size/variant. "" when there is no usable price."""
    if d.get('priceType') in ('sizes', 'variants') and d.get('variants'):
        low = min(v['priceMinor'] for v in d['variants'] if v.get('priceMinor', 0) > 0) if any(
            v.get('priceMinor', 0) > 0 for v in d['variants']) else 0
        return f'desde {money(low, currency)}' if low > 0 else ''
    p = d.get('priceMinor') or 0
    return money(p, currency) if p > 0 else ''


def usable(d):
    return d.get('status') == 'active' and d.get('availability', 'available') == 'available' and bool(
        str(d.get('name', '')).strip()) and bool(dish_price(d))


def pick_dishes(menu, n, seed):
    """Dish of the week first, then a stable pick that rotates with `seed` (e.g. the ISO date), so two days differ."""
    pool = [d for d in menu.get('dishes', []) if usable(d)]
    pool.sort(key=lambda d: hashlib.sha256(f'{seed}:{d["id"]}'.encode()).hexdigest())
    star = menu.get('dishOfTheWeek')
    pool.sort(key=lambda d: 0 if star and d['id'] == star else 1)
    return pool[:n]


def _short(name, n=38):
    name = re.sub(r'\s+', ' ', str(name)).strip()
    return name if len(name) <= n else name[:n - 1].rstrip() + '…'


def build_job(payload, seed, kind='top3', brand='dinidine', client=None, require_consent=False):
    """payload = the Agent API menu response. Returns the job dict, or None when the menu is too thin for a video."""
    if kind not in KINDS:
        raise ValueError(f'kind must be one of {KINDS}')
    biz = payload.get('business') or {}
    menu = payload.get('menu') or {}
    cur = menu.get('currency') or 'USD'
    name = _short(biz.get('name') or biz.get('slug') or 'tu restaurante', 40)
    slug = slugify(client or biz.get('slug') or name)
    need = 3 if kind == 'top3' else 1
    dishes = pick_dishes(menu, need, seed)
    if len(dishes) < need:
        return None
    jid = f'menu-{slug}-{kind}-{seed}'[:80]
    title = f'{name}: así se ve su menú digital'
    scenes = [{'type': 'hook', 'kicker': 'Menú digital',
               'title': f'Así se ve el menú de **{name}**',
               'speak': f'Así se ve el menú digital de {name}.'}]
    if kind == 'top3':
        pts = [f'**{_short(d["name"])}**  {dish_price(d, cur)}' for d in dishes]
        names = ', '.join(_short(d['name']) for d in dishes[:-1]) + ' y ' + _short(dishes[-1]['name'])
        scenes.append({'type': 'step', 'title': 'Platos que **tus clientes ven**',
                       'speak': f'Tus clientes ven {names}, con su precio claro y sin pedir el menú impreso.',
                       'points': pts})
    else:
        d = dishes[0]
        desc = re.sub(r'\s+', ' ', d.get('description') or '').strip()
        pts = [f'**{_short(d["name"])}**  {dish_price(d, cur)}'] + ([_short(desc, 60)] if desc else [])
        scenes.append({'type': 'step', 'title': 'Un plato, **bien presentado**',
                       'speak': f'{_short(d["name"])}. Así lo ve el cliente desde su celular.',
                       'points': pts})
    scenes.append({'type': 'outro', 'title': 'Tu menú, claro y en tu celular.',
                   'cta': 'Escríbenos para verlo en tu restaurante',
                   'speak': 'Tu menú, claro y en el celular de tus clientes. Escríbenos y lo vemos en tu restaurante.'})
    return {
        'id': jid, 'brand': brand, 'template': 'menu', 'client': client if require_consent else None, 'title': title,
        'caption': f'Así se ve el menú digital de {name}. Platos y precios claros, sin menú impreso. '
                   'Si quieres ver cómo quedaría el tuyo, escríbenos.',
        'hashtags': ['#restaurantes', '#menudigital', '#negociolatino', '#Gwinnett'],
        'cta_text': 'Escríbenos para verlo en tu restaurante',
        'verify': ([f'Confirma que {name} sigue de acuerdo en aparecer en el video y que los precios están vigentes.']
                   if require_consent else
                   [f'Sale el nombre y el menú de {name}: revisa que los precios estén vigentes antes de aprobar.']) + [
                   f'Menú leído de la plataforma el {seed}.'],
        'scenes': scenes,
    }
