"""Scene templates. A scene = one JSON object in the job. Types: hook | step (alias tip) | outro.

Text supports **accent** markup. Visuals for step/tip:
  "points": ["...", ...]                       checklist card, items appear along the narration
  "visual": {"kind":"phone","screen":"profile","fields":[["Label","Value"],...]}
  "visual": {"kind":"phone","screen":"chat","messages":[{"from":"cliente|negocio","text":"..."}]}
  "visual": {"kind":"phone","screen":"clip","path":"clients/<slug>/menu.mp4"}      (automatic capture, see connectors/capture.py)
  "visual": {"kind":"image","path":"relative/or/absolute.png"}   (restaurant screenshots, TV screens, hero image)
"""
import os
from PIL import Image, ImageDraw
from .draw import W, H, ss, sm, ph, back, paste, wrap, pill, card, fit_image, check_icon
from .brand import ROOT

GRAY = (130, 118, 105)


# ---------- rich text ----------
def rich_words(text):
    """Words as lists of (piece, highlighted) so punctuation glued to a **marked** word stays glued."""
    out, on = [], False
    for tok in text.split():
        pieces = []
        for k, p in enumerate(tok.split('**')):
            if k > 0:
                on = not on
            if p:
                pieces.append((p, on))
        if pieces:
            out.append(pieces)
    return out


def _wlen(d, word, font):
    return sum(d.textlength(p, font=font) for p, _ in word)


def rich_lines(d, text, font, maxw):
    lines, cur, cw = [], [], 0
    sp = d.textlength(' ', font=font)
    for word in rich_words(text):
        wl = _wlen(d, word, font)
        if cur and cw + sp + wl > maxw:
            lines.append(cur)
            cur, cw = [], 0
        cw += (sp if cur else 0) + wl
        cur.append(word)
    if cur:
        lines.append(cur)
    return lines


def draw_line(d, line, font, x, y, col, acc, center=False):
    sp = d.textlength(' ', font=font)
    tw = sum(_wlen(d, w, font) for w in line) + sp * (len(line) - 1)
    if center:
        x = x - tw / 2
    for word in line:
        for p, hl in word:
            d.text((x, y), p, font=font, fill=acc if hl else col)
            x += d.textlength(p, font=font)
        x += sp


def title_block(ctx, base, text, x, y, maxw, size, t, t0=0.1, center=False, col=None):
    b = ctx.brand
    d = ImageDraw.Draw(base)
    f = b.font('display', size)
    lines = rich_lines(d, text, f, maxw)
    lh = int(size * 1.12)
    for i, ln in enumerate(lines):
        u = back((t - t0 - 0.12 * i) / 0.5)
        if u <= 0:
            continue
        layer = Image.new('RGBA', (W, lh + 20), (0, 0, 0, 0))
        draw_line(ImageDraw.Draw(layer), ln, f, x, 0, col or b.INK, b.ACC, center)
        paste(base, layer, 0, y + i * lh + (1 - u) * 40, alpha=min(1, u * 1.2))
    return y + len(lines) * lh


# ---------- visuals ----------
def reveal_times(sc, n):
    v = max(sc.voice, 1.0)
    return [0.35 + (v - 0.9) * j / max(n, 1) for j in range(n)]


def points_card(ctx, base, sc, pts, t, y0, h):
    b = ctx.brand
    d0 = ImageDraw.Draw(base)
    f = b.font('body', 58)
    rows = [rich_lines(d0, p, f, 730) for p in pts]
    heights = [len(r) * 72 + 56 for r in rows]
    need = sum(heights) + 50
    cw, ch = 940, min(h, need)
    y0 = y0 + max(0, int((h - ch) * 0.3))
    c = card(cw, ch)
    u = back(t / 0.45)
    paste(base, c, 70, y0 + (1 - u) * 30, alpha=min(1, u * 1.3))
    times = reveal_times(sc, len(pts))
    y = y0 + 34
    chk = check_icon(64, b.WHITE)
    for ln, hgt, tt in zip(rows, heights, times):
        a = ph(t, tt, tt + 0.35)
        if a > 0:
            layer = Image.new('RGBA', (W, hgt + 10), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            dot = ss((64, 64), lambda dr, s: dr.ellipse([0, 0, 64 * s, 64 * s], fill=b.OK + (255,)), 3)
            layer.paste(dot, (110, 18), dot)
            layer.paste(chk, (110, 18), chk)
            for i, l in enumerate(ln):
                draw_line(ld, l, f, 200, 14 + i * 72, b.INK, b.ACC)
            paste(base, layer, 0, y + (1 - a) * 24, alpha=a)
        y += hgt


_phone_cache = {}


def clip_frames(ctx, path, sw, sh):
    """Extract a captured clip once to JPEG frames sized for the phone screen; returns (dir, count)."""
    import hashlib
    import subprocess
    p = path if os.path.isabs(path) else os.path.join(ROOT, path)
    key = ('clip', p, os.path.getmtime(p))
    if key not in ctx.cache:
        d = os.path.join(ROOT, 'build', 'clips', hashlib.md5(f'{p}{os.path.getmtime(p)}'.encode()).hexdigest()[:12])
        if not os.path.isdir(d):
            os.makedirs(d + '.tmp', exist_ok=True)
            subprocess.check_call(['ffmpeg', '-y', '-loglevel', 'error', '-i', p, '-vf',
                                   f'fps=30,scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh}', '-q:v', '3',
                                   os.path.join(d + '.tmp', '%05d.jpg')])
            os.rename(d + '.tmp', d)
        ctx.cache[key] = (d, len(os.listdir(d)))
    return ctx.cache[key]


def clip_frame(ctx, path, t, sw, sh):
    d, n = clip_frames(ctx, path, sw, sh)
    i = min(n - 1, int(t * 30) % max(n, 1)) if t * 30 < n else n - 1
    return Image.open(os.path.join(d, f'{i + 1:05d}.jpg')).convert('RGBA')


def phone_body(b, w=440, h=800):
    k = (b.slug, w, h)
    if k not in _phone_cache:
        def f(d, s):
            d.rounded_rectangle([8 * s, 18 * s, (w - 2) * s, (h + 10) * s], radius=60 * s, fill=(65, 38, 24, 50))
            d.rounded_rectangle([0, 0, (w - 10) * s, (h) * s], radius=58 * s, fill=b.INK + (255,))
            d.rounded_rectangle([160 * s, 14 * s, 270 * s, 30 * s], radius=8 * s, fill=(30, 18, 10, 255))
        _phone_cache[k] = ss((w, h + 20), f, 3)
    return _phone_cache[k]


def phone_screen(ctx, sc, vis, t, sw=412, sh=744):
    b = ctx.brand
    if vis.get('screen') == 'clip':
        return clip_frame(ctx, vis['path'], t, sw, sh)
    im = Image.new('RGBA', (sw, sh), (247, 243, 235, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, sw, 150], fill=b.INK + (255,))
    d.ellipse([22, 58, 94, 130], fill=b.ACC + (255,))
    d.text((112, 78), vis.get('header', 'Tu restaurante'), font=b.font('display', 34), fill=b.WHITE)
    d.text((112, 120), vis.get('sub', 'Cuenta de empresa'), font=b.font('soft', 24), fill=(225, 210, 190))
    if vis.get('screen') == 'chat':
        msgs = vis.get('messages', [])
        times = reveal_times(sc, len(msgs))
        y = 180
        f = b.font('body', 30)
        for m, tt in zip(msgs, times):
            a = ph(t, tt, tt + 0.3)
            if a <= 0:
                continue
            lines = wrap(d, m['text'], f, 270)
            bh = len(lines) * 40 + 28
            mine = m.get('from') == 'negocio'
            bw = max(d.textlength(l, font=f) for l in lines) + 36
            x0 = sw - 20 - bw if mine else 20
            layer = Image.new('RGBA', (sw, bh + 10), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            ld.rounded_rectangle([x0, 0, x0 + bw, bh], radius=24, fill=(b.ACC + (255,)) if mine else (255, 255, 255, 255), outline=(225, 212, 185, 255), width=2)
            for i, l in enumerate(lines):
                ld.text((x0 + 18, 14 + i * 40), l, font=f, fill=b.INK)
            layer.putalpha(layer.getchannel('A').point(lambda v, a=a: int(v * a)))
            im.paste(layer, (0, int(y + (1 - a) * 18)), layer)
            y += bh + 16
    else:  # profile fields
        fields = vis.get('fields', [])
        times = reveal_times(sc, len(fields))
        y = 176
        fl, fv = b.font('soft', 24), b.font('body', 32)
        for (lab, val), tt in zip(fields, times):
            a = ph(t, tt, tt + 0.3)
            if a > 0:
                layer = Image.new('RGBA', (sw, 112), (0, 0, 0, 0))
                ld = ImageDraw.Draw(layer)
                ld.rounded_rectangle([16, 0, sw - 16, 100], radius=22, fill=(255, 255, 255, 255), outline=(225, 212, 185, 255), width=2)
                ld.text((38, 14), lab, font=fl, fill=GRAY)
                vf = fv
                while ld.textlength(val, font=vf) > sw - 150 and vf.size > 20:
                    vf = b.font('body', vf.size - 2)
                ld.text((38, 50), val, font=vf, fill=b.INK)
                ck = check_icon(34, b.OK)
                layer.paste(ck, (sw - 70, 33), ck)
                im.paste(layer, (0, int(y + (1 - a) * 18)), layer)
            y += 118
    return im


def phone(ctx, base, sc, vis, t, y0):
    b = ctx.brand
    body = phone_body(b)
    u = back(t / 0.5)
    x = (W - 440) // 2
    yy = y0 + (1 - u) * 60
    paste(base, body, x, yy, alpha=min(1, u * 1.3))
    scr = phone_screen(ctx, sc, vis, t)
    mask = ss(scr.size, lambda d, s: d.rounded_rectangle([0, 0, scr.width * s, scr.height * s], radius=44 * s, fill=(255, 255, 255, 255)), 2)
    scr.putalpha(mask.getchannel('A'))
    paste(base, scr, x + 14, yy + 40, alpha=min(1, u * 1.3))


def image_visual(ctx, base, sc, vis, t, y0, h):
    p = vis['path']
    p = p if os.path.isabs(p) else os.path.join(ROOT, p)
    key = ('img', p, h)
    if key not in ctx.cache:
        ctx.cache[key] = fit_image(Image.open(p), 940, h, 34)
    u = back(t / 0.5)
    paste(base, card(960, h + 20), 60, y0 - 4 + (1 - u) * 30, alpha=min(1, u * 1.3))
    paste(base, ctx.cache[key], 70, y0 + 2 + (1 - u) * 30, alpha=min(1, u * 1.3))


# ---------- scene types ----------
def scene_hook(ctx, base, sc, t):
    b = ctx.brand
    ctx.brand.logo_on(base, 60, 50, 300)
    k = sc.data.get('kicker')
    if k:
        u = back(t / 0.5)
        paste(base, pill(k, b.font('display', 50), b.WHITE, b.INK, padx=40, pady=10), 70, 185 + (1 - u) * -30, alpha=min(1, u * 1.3))
    title_block(ctx, base, sc.data['title'], 70, 300, 940, 104, t)


def scene_step(ctx, base, sc, t):
    b = ctx.brand
    b.logo_on(base, 60, 50, 300)
    d = sc.data
    n = d.get('n')
    y = 190
    if n is not None:
        u = back(t / 0.5)
        badge = ss((150, 150), lambda dr, s: (dr.ellipse([0, 0, 150 * s, 150 * s], fill=b.ACC + (255,)), dr.ellipse([8 * s, 8 * s, 142 * s, 142 * s], outline=(255, 255, 255, 120), width=4 * s)), 3)
        ImageDraw.Draw(badge).text((75, 78), str(n), font=b.font('display', 92), fill=b.INK, anchor='mm')
        paste(base, badge, 70, y + (1 - u) * -30, alpha=min(1, u * 1.3))
        end = title_block(ctx, base, d['title'], 250, y + 10, 760, 74, t)
        end = max(end, y + 170)
    else:
        end = title_block(ctx, base, d['title'], 70, y, 940, 80, t)
    vy = end + 36
    vh = 1330 - vy
    vis = d.get('visual')
    if vis and vis.get('kind') == 'phone':
        phone(ctx, base, sc, vis, t, vy)
    elif vis and vis.get('kind') == 'image':
        image_visual(ctx, base, sc, vis, t, vy, vh)
    elif d.get('points'):
        points_card(ctx, base, sc, d['points'], t, vy, vh)


def scene_outro(ctx, base, sc, t):
    b = ctx.brand
    u = back(t / 0.6)
    if b.logo is not None:
        lw = 560
        lg = b.logo.resize((lw, int(b.logo.height * lw / b.logo.width)), Image.LANCZOS)
        paste(base, lg, (W - lw) // 2, 170 + (1 - u) * -30, alpha=min(1, u * 1.3))
    end = title_block(ctx, base, sc.data['title'], W / 2, 430, 900, 84, t, t0=0.2, center=True)
    cta = sc.data.get('cta')
    if cta:
        a = back((t - 0.8) / 0.5)
        pl = pill(cta, b.font('display', 56), b.INK, b.ACC, padx=56, pady=20)
        paste(base, pl, (W - pl.width) // 2, end + 40 + (1 - a) * 30, alpha=min(1, a * 1.3))


TYPES = {'hook': scene_hook, 'step': scene_step, 'tip': scene_step, 'outro': scene_outro}
