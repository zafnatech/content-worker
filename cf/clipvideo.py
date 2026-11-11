"""Clip pieces: a REAL animated dish (or hero) clip from the restaurant's profile, vertical 1080x1920, with a hook,
the dish name + real price, a closing line and original music. No AI is called here (the clip already exists in the
platform), no voice, no frame loop: Pillow draws a few transparent PNGs and ffmpeg composes them. A few seconds per piece.

Queue job (queue/<id>.json), fields:
  id, type "clip", run_after "2026-11-10T05:30:00Z", brand, client (slug), business_name, clip_url, dish, price_minor,
  currency, price_type (base|sizes), hook (<= 8 words, or hook_id from brands/<brand>/hooks.json), caption, hashtags, cta,
  end_title, music (cumbia|lofi|urbano|bright; default rotates by date), post_date "YYYY-MM-DD", times {network: "HH:MM"} (optional)
"""
import os
import re
import json
import subprocess
import urllib.request
import urllib.error
from PIL import Image, ImageDraw, ImageFilter
from .brand import Brand
from .music import make_preset, style_for, STYLES

W, H, FPS = 1080, 1920, 30
MAX_CLIP_BYTES = 120 * 1024 * 1024
MAX_SECONDS = 15.0
MIN_SECONDS = 7.0


class ClipError(Exception):
    pass


# ---------------------------------------------------------------------------------------------------------------- data
def fmt_price(minor, currency='USD', price_type='base'):
    """Real price from the menu, never rounded up or invented. 'sizes' means the dish has several sizes: 'Desde'."""
    if minor is None:
        return ''
    amount = int(minor) / 100
    if (currency or 'USD').upper() == 'USD':
        s = f'${amount:.0f}' if int(minor) % 100 == 0 else f'${amount:.2f}'
    else:
        s = f'{amount:.2f} {currency.upper()}'
    return ('Desde ' + s) if price_type == 'sizes' else s


def words(text):
    return len(re.findall(r'\S+', text or ''))


def pick_hook(job, brand_slug):
    """Explicit hook, or one from the bank (hook_id). Templates are filled with real data. <= 8 words, always."""
    if job.get('hook'):
        hook = job['hook']
    elif job.get('hook_id'):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'brands', brand_slug, 'hooks.json')
        with open(path, encoding='utf-8') as f:
            bank = {h['id']: h for h in json.load(f)['hooks']}
        if job['hook_id'] not in bank:
            raise ClipError(f'hook_id {job["hook_id"]} no está en hooks.json')
        hook = bank[job['hook_id']]['text']
    else:
        raise ClipError('el job necesita hook u hook_id')
    for key, field in (('{restaurante}', 'business_name'), ('{plato}', 'dish')):
        if key in hook:
            if not job.get(field):
                raise ClipError(f'el hook usa {key} pero el job no trae {field}')
            hook = hook.replace(key, job[field])
    if '{' in hook:
        raise ClipError(f'hook con datos sin llenar: {hook}')
    if words(hook) > 8:
        raise ClipError(f'hook de {words(hook)} palabras (máximo 8): {hook}')
    return hook


PAGE_HOSTS = ('.zafnatech.com', '.digidine.us', '.dinidine.com')   # + WORKER_PAGE_HOSTS (comma list) for a restaurant's own domain


def page_host_ok(url):
    """A public https page of ours (or of a client domain listed in WORKER_PAGE_HOSTS). Never an arbitrary site."""
    from urllib.parse import urlparse
    u = urlparse(str(url))
    host = (u.hostname or '').lower()
    if u.scheme != 'https' or not host or u.username or u.password:
        return False
    extra = tuple(h.strip().lower() for h in os.environ.get('WORKER_PAGE_HOSTS', '').split(',') if h.strip())
    return any(host == h.lstrip('.') or host.endswith(h if h.startswith('.') else '.' + h) for h in PAGE_HOSTS + extra)


def validate(job):
    source = 'page_url' if job.get('page_url') else 'clip_url'
    missing = [k for k in ('id', source, 'dish', 'caption') if not job.get(k)]
    if missing:
        raise ClipError('faltan campos: ' + ', '.join(missing))
    if source == 'page_url':
        if not page_host_ok(job['page_url']):
            raise ClipError('page_url debe ser una página https pública de DiniDine (o de un dominio en WORKER_PAGE_HOSTS)')
    elif not str(job['clip_url']).startswith('https://'):
        raise ClipError('clip_url debe ser https')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,90}', job['id']):
        raise ClipError('id inválido (minúsculas, números y guiones)')
    if words(job['caption']) > 45:
        raise ClipError('caption demasiado largo (máx. 45 palabras)')
    if job.get('music') and job['music'] not in STYLES:
        raise ClipError(f'music debe ser una de {STYLES}')


def public_text_job(job, hook):
    """What the guardrails read: everything a viewer will see or read."""
    return {'brand': job.get('brand', 'dinidine'), 'hook': hook, 'dish': job.get('dish'), 'caption': job.get('caption'),
            'hashtags': job.get('hashtags', []), 'cta': job.get('cta'), 'end_title': job.get('end_title')}


# ------------------------------------------------------------------------------------------------------------- download
def candidate_urls(url):
    """Cloudinary clips are stored at w_720; try a sharper 1080 rendition first and fall back to the stored one."""
    out = []
    if 'res.cloudinary.com' in url and 'w_720' in url:
        out.append(url.replace('w_720', 'w_1080'))
    out.append(url)
    return out


def download(url, dest, opener=urllib.request.urlopen):
    last = None
    for u in candidate_urls(url):
        try:
            req = urllib.request.Request(u, headers={'User-Agent': 'dinidine-content-worker/1.0'})
            with opener(req, timeout=60) as r:
                size = 0
                with open(dest, 'wb') as f:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_CLIP_BYTES:
                            raise ClipError('el clip pesa más de 120 MB')
                        f.write(chunk)
            if size < 10_000:
                raise ClipError(f'descarga sospechosamente pequeña ({size} bytes)')
            probe(dest)   # raises if it is not a playable video
            return u
        except (urllib.error.URLError, OSError, ClipError, ValueError) as e:
            last = e
    raise ClipError(f'no pude bajar el clip ({last})')


def capture_page(url, dest, seconds=8.0):
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from connectors import capture
        capture.capture(url, dest, seconds=min(max(seconds, MIN_SECONDS), MAX_SECONDS - 3), size=(1170, 2082), scale=3)
    except Exception as e:   # Chromium missing, page down, timeout...
        raise ClipError(f'no pude grabar la pantalla de {url} ({type(e).__name__}: {e})')


def probe(path):
    p = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height:format=duration',
                        '-of', 'json', path], capture_output=True, text=True)
    if p.returncode != 0:
        raise ClipError('el archivo no es un video válido')
    j = json.loads(p.stdout)
    st = (j.get('streams') or [{}])[0]
    dur = float((j.get('format') or {}).get('duration') or 0)
    if not st.get('width') or dur <= 0.5:
        raise ClipError('el video no tiene imagen o dura menos de medio segundo')
    return int(st['width']), int(st['height']), dur


# ------------------------------------------------------------------------------------------------------------- overlays
def _balanced(draw, words_, font, n):
    """Splits words into n lines with the most even widths (no lonely last word)."""
    import itertools
    best = None
    for cuts in itertools.combinations(range(1, len(words_)), n - 1):
        parts = [' '.join(words_[i:j]) for i, j in zip((0,) + cuts, cuts + (len(words_),))]
        widths = [draw.textlength(p_, font=font) for p_ in parts]
        score = max(widths)
        if best is None or score < best[0]:
            best = (score, parts)
    return best


def _fit_lines(draw, text, font_loader, max_w, sizes, max_lines):
    """Biggest size that fits in <= max_lines balanced lines; fewer lines are preferred over a smaller size down to
    the second-biggest size, so a hook never ends with one orphan word."""
    ws = text.split()
    for lines_allowed in range(1, max_lines + 1):
        for size in sizes:
            font = font_loader(size)
            if lines_allowed > len(ws):
                break
            res = _balanced(draw, ws, font, lines_allowed) if lines_allowed > 1 else (draw.textlength(text, font=font), [text])
            if res and res[0] <= max_w:
                return font, res[1], size
    font = font_loader(sizes[-1])
    return font, _balanced(draw, ws, font, min(max_lines, len(ws)))[1] if len(ws) > 1 else [text], sizes[-1]


def _outlined(draw, xy, text, font, fill, stroke=7, anchor='la'):
    x, y = xy
    draw.text((x + 3, y + 5), text, font=font, fill=(0, 0, 0, 120), anchor=anchor, stroke_width=stroke, stroke_fill=(0, 0, 0, 120))
    draw.text((x, y), text, font=font, fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=(30, 18, 10, 255))


def base_png(brand, path):
    """Top/bottom shade so text reads on any food footage + the DiniDine mark in a small cream chip (top-left)."""
    import numpy as np
    ys = np.arange(H, dtype=np.float64)
    a = np.zeros(H)
    top = ys < 640
    a[top] = 150 * (1 - ys[top] / 640) ** 1.6
    bot = ys > 1100
    a[bot] = 190 * ((ys[bot] - 1100) / (H - 1100)) ** 1.3
    arr = np.zeros((H, W, 4), dtype=np.uint8)
    arr[..., 0], arr[..., 1], arr[..., 2] = 15, 8, 4
    arr[..., 3] = a.astype(np.uint8)[:, None]
    img = Image.fromarray(arr, 'RGBA')
    if brand.logo is not None:
        chip = Image.new('RGBA', (300, 110), (0, 0, 0, 0))
        ImageDraw.Draw(chip).rounded_rectangle([0, 0, 299, 109], radius=34, fill=(251, 247, 238, 240))
        lg = brand.logo.copy()
        lg.thumbnail((236, 70), Image.LANCZOS)
        chip.paste(lg, ((300 - lg.width) // 2, (110 - lg.height) // 2), lg)
        img.alpha_composite(chip, (56, 64))
    img.save(path)


PHONE = (260, 500, 560, 996)   # x, y, w, h of the screen inside the 1080x1920 frame (inside the platforms' safe zones)


def phone_base_png(brand, path):
    """Dark background + phone bezel with a transparent screen hole where the page recording shows through."""
    x, y, w, h = PHONE
    img = Image.new('RGBA', (W, H), brand.INK + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x - 22, y - 22, x + w + 22, y + h + 22], radius=78, fill=(20, 20, 22, 255), outline=brand.ACC + (255,), width=4)
    mask = Image.new('L', (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([x, y, x + w, y + h], radius=56, fill=255)
    img.paste((0, 0, 0, 0), (0, 0), mask)
    if brand.logo is not None:
        chip = Image.new('RGBA', (300, 110), (0, 0, 0, 0))
        ImageDraw.Draw(chip).rounded_rectangle([0, 0, 299, 109], radius=34, fill=(251, 247, 238, 240))
        lg = brand.logo.copy()
        lg.thumbnail((236, 70), Image.LANCZOS)
        chip.paste(lg, ((300 - lg.width) // 2, (110 - lg.height) // 2), lg)
        img.alpha_composite(chip, (56, 64))
    img.save(path)


def hook_png(brand, text, path):
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font, lines, size = _fit_lines(d, text, lambda s: brand.font('display', s), 900, (104, 92, 80, 70), 3)
    lh = int(size * 1.12)
    y = 200 if len(lines) < 3 else 180
    for i, l in enumerate(lines):
        last = i == len(lines) - 1
        _outlined(d, (W // 2, y + i * lh), l, font, brand.ACC + (255,) if last and len(lines) > 1 else (255, 255, 255, 255), anchor='ma')
    img.save(path)


def info_png(brand, dish, price, biz, path):
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, y0, w, h = 60, 1250, 960, 250
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=44, fill=brand.INK + (232,))
    d.rounded_rectangle([x0, y0, x0 + 14, y0 + h], radius=7, fill=brand.ACC + (255,))
    pill_w = 0
    if price:
        pf = brand.font('display', 62)
        pill_w = int(d.textlength(price, font=pf)) + 70
    font, lines, size = _fit_lines(d, dish, lambda s: brand.font('display', s), w - 90, (72, 64, 56, 48), 2)
    ty = y0 + 28
    for l in lines:
        d.text((x0 + 48, ty), l, font=font, fill=(255, 255, 255, 255))
        ty += int(size * 1.08)
    by = y0 + h - 84
    if biz:
        d.text((x0 + 48, by + 14), biz, font=brand.font('soft', 40), fill=brand.ACC + (255,))
    if price:
        px1, px0 = x0 + w - 32, x0 + w - 32 - pill_w
        d.rounded_rectangle([px0, by - 6, px1, by + 70], radius=38, fill=brand.ACC + (255,))
        d.text(((px0 + px1) // 2, by + 32), price, font=brand.font('display', 52), fill=brand.INK + (255,), anchor='mm')
    img.save(path)


def end_png(brand, title, sub, path):
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, y0, w, h = 60, 1250, 960, 250
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=44, fill=brand.ACC + (250,))
    font, lines, size = _fit_lines(d, title, lambda s: brand.font('display', s), w - 90, (78, 68, 60, 52), 2)
    total = len(lines) * int(size * 1.1) + (56 if sub else 0)
    ty = y0 + (h - total) // 2
    for l in lines:
        d.text((W // 2, ty), l, font=font, fill=brand.INK + (255,), anchor='ma')
        ty += int(size * 1.1)
    if sub:
        d.text((W // 2, ty + 8), sub, font=brand.font('soft', 38), fill=brand.INK + (255,), anchor='ma')
    img.save(path)


# ----------------------------------------------------------------------------------------------------------------- ffmpeg
def timings(dur):
    hook_end = min(3.0, dur * 0.38)
    end_len = min(2.3, dur * 0.28)
    return hook_end, dur - end_len


def build_filter(src_w, src_h, dur, phone=False):
    """filter_complex for inputs: 0 clip, 1 base.png, 2 hook.png, 3 info.png, 4 end.png, 5 music.
    Portrait footage fills the frame; landscape/square footage sits in a 1080x1000 window over a blurred copy of itself."""
    hook_end, end_start = timings(dur)
    if phone:
        px, py, pw, ph = PHONE
        bg = (f'[0:v]fps={FPS},setpts=PTS-STARTPTS,scale={pw}:{ph}:force_original_aspect_ratio=increase,crop={pw}:{ph},setsar=1,'
              f'pad={W}:{H}:{px}:{py}:color=black[bg];')
    elif src_w / src_h <= 0.75:
        bg = f'[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS},setpts=PTS-STARTPTS[bg];'
    else:
        bg = (f'[0:v]fps={FPS},setpts=PTS-STARTPTS,split[a][b];'
              f'[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=38:6,eq=brightness=-0.16:saturation=1.1[bl];'
              f'[b]scale={W}:1000:force_original_aspect_ratio=increase,crop={W}:1000,setsar=1[fg];[bl][fg]overlay=0:400[bg];')

    def fade(i, tin, tout=None):
        f = f'[{i}:v]format=rgba,fade=t=in:st={tin:.2f}:d=0.28:alpha=1'
        if tout is not None:
            f += f',fade=t=out:st={tout:.2f}:d=0.28:alpha=1'
        return f
    g = bg
    g += '[bg][1:v]overlay=0:0[v1];'
    g += fade(2, 0.15, hook_end - 0.28) + '[hk];[v1][hk]overlay=0:0[v2];'
    g += fade(3, hook_end - 0.1, end_start - 0.3) + '[inf];[v2][inf]overlay=0:0[v3];'
    g += fade(4, end_start) + '[en];[v3][en]overlay=0:0,format=yuv420p[v];'
    g += f'[5:a]atrim=0:{dur:.2f},afade=t=in:d=0.3,afade=t=out:st={max(0, dur - 1.0):.2f}:d=1.0,volume=2.6,alimiter=limit=0.93[a]'
    return g


def compose(clip_path, overlays, music_path, out_path, src_w, src_h, src_dur, phone=False):
    dur = min(max(src_dur, MIN_SECONDS), MAX_SECONDS)
    loops = int(dur // src_dur) if src_dur < dur else 0
    # Every thread count is explicit: ffmpeg otherwise sizes decoders, filters and x264 by the host's CPU count, and on a
    # big Render host that blew past the 2 GB of the 1c-2g plan ("Out of memory (used over 2Gi)", 10 Nov 2026).
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-threads', '1', '-stream_loop', str(loops), '-t', f'{dur:.2f}', '-i', clip_path]
    for p in overlays:
        cmd += ['-threads', '1', '-loop', '1', '-framerate', str(FPS), '-t', f'{dur:.2f}', '-i', p]
    cmd += ['-threads', '1', '-i', music_path, '-filter_complex_threads', '1', '-filter_complex', build_filter(src_w, src_h, dur, phone),
            '-map', '[v]', '-map', '[a]',
            '-c:v', 'libx264', '-threads', '2', '-x264-params', 'rc-lookahead=10:sliced-threads=0',
            '-preset', 'veryfast', '-crf', '20', '-r', str(FPS), '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '160k', '-t', f'{dur:.2f}', '-movflags', '+faststart', out_path]
    tmp = out_path.replace('.mp4', '.tmp.mp4')
    cmd[-1] = tmp
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise ClipError('ffmpeg falló: ' + (p.stderr or '').strip().splitlines()[-1][:200])
    os.replace(tmp, out_path)
    return dur


# ----------------------------------------------------------------------------------------------------------------- main
def render(job, out_dir, date_ordinal=None, fetch=download, work_dir=None):
    """Returns (manifest_path, manifest). Raises ClipError with a message a person can read."""
    import datetime
    from . import guardrails
    validate(job)
    brand_slug = job.get('brand', 'dinidine')
    hook = pick_hook(job, brand_slug)
    hits = guardrails.check(public_text_job(job, hook), brand_slug)
    if hits:
        raise ClipError('bloqueado por las reglas de la marca: ' + ', '.join(hits))
    brand = Brand(brand_slug)
    os.makedirs(out_dir, exist_ok=True)
    work = work_dir or os.path.join(out_dir, '_work')
    os.makedirs(work, exist_ok=True)
    clip = os.path.join(work, 'clip.mp4')
    if job.get('page_url'):
        # Screen recording of a public menu: headless Chromium at phone size, no login, nothing typed (connectors/capture.py).
        used_url = job['page_url']
        capture_page(used_url, clip, float(job.get('seconds') or 8))
    else:
        used_url = fetch(job['clip_url'], clip)
    w, h, d = probe(clip)
    price = fmt_price(job.get('price_minor'), job.get('currency', 'USD'), job.get('price_type', 'base'))
    ov = [os.path.join(work, n) for n in ('base.png', 'hook.png', 'info.png', 'end.png')]
    phone = bool(job.get('page_url'))
    if phone:
        phone_base_png(brand, ov[0])
        Image.new('RGBA', (W, H), (0, 0, 0, 0)).save(ov[2])   # no info plate: it would cover the menu
    else:
        base_png(brand, ov[0])
        info_png(brand, job['dish'], price, job.get('business_name', ''), ov[2])
    hook_png(brand, hook, ov[1])
    end_png(brand, job.get('end_title') or '¿Tu menú se ve así?', job.get('end_sub') or 'DiniDine · menús digitales', ov[3])
    ordinal = date_ordinal if date_ordinal is not None else datetime.date.today().toordinal()
    style = job.get('music') or style_for(ordinal)
    music = os.path.join(work, 'music.wav')
    make_preset(music, min(max(d, MIN_SECONDS), MAX_SECONDS) + 0.3, style, seed=ordinal)
    mp4 = os.path.join(out_dir, job['id'] + '.mp4')
    dur = compose(clip, ov, music, mp4, w, h, d, phone=phone)
    verify = list(job.get('verify') or [])
    verify.append('Clip animado a partir de la foto real del plato: revisa la etiqueta de contenido IA de cada red antes de aprobar.')
    manifest = {'id': job['id'], 'title': f'{job["dish"]} · {job.get("business_name", "")}'.strip(' ·')[:100],
                'voice_chars': 0, 'voice_cost_usd_est': 0.0, 'brand': brand_slug, 'client': job.get('client'),
                'consent': 'clip del perfil real del restaurante en la plataforma', 'draft': False,
                'duration_s': round(dur, 1), 'voice': 'sin voz (texto + música)', 'caption': job['caption'],
                'hashtags': job.get('hashtags', []), 'cta': job.get('cta', ''), 'captions': job.get('captions', {}),
                'titles': job.get('titles', {}), 'ai_disclosure': True, 'verify_before_publish': verify,
                'schedule': job.get('schedule'), 'lineage': job.get('lineage'), 'file': mp4,
                'format': 'plato-animado', 'music_style': style, 'hook': hook, 'source_clip': used_url}
    mpath = os.path.join(out_dir, job['id'] + '.json')
    with open(mpath, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return mpath, manifest
