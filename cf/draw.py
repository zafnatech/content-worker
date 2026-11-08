"""Drawing helpers shared by every template (1080x1920 vertical)."""
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H, FPS = 1080, 1920, 30


def sm(x):
    x = min(1, max(0, x))
    return x * x * (3 - 2 * x)


def ph(t, a, b):
    return sm((t - a) / (b - a)) if b > a else float(t >= a)


def back(x):
    x = min(1, max(0, x))
    c = 1.70158
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def ss(size, draw_fn, scale=3):
    """Draw at `scale`x and downsample: smooth edges."""
    im = Image.new('RGBA', (size[0] * scale, size[1] * scale), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(im), scale)
    return im.resize(size, Image.LANCZOS)


def paste(base, im, x, y, alpha=1.0):
    if alpha <= 0:
        return
    if alpha < 1:
        im = im.copy()
        im.putalpha(im.getchannel('A').point(lambda v: int(v * alpha)))
    base.paste(im, (int(x), int(y)), im)


def scaled(im, s):
    if abs(s - 1) < 1e-3:
        return im
    return im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)


def wrap(draw, text, font, maxw):
    lines, cur = [], ''
    for w_ in text.split():
        tt = (cur + ' ' + w_).strip()
        if draw.textlength(tt, font=font) > maxw and cur:
            lines.append(cur)
            cur = w_
        else:
            cur = tt
    if cur:
        lines.append(cur)
    return lines


def pill(text, font, fg, bg, padx=44, pady=18, outline=None):
    tmp = ImageDraw.Draw(Image.new('RGBA', (10, 10)))
    bb = tmp.textbbox((0, 0), text, font=font, anchor='lt')
    w, h = int(bb[2] - bb[0] + 2 * padx), int(font.size + 2 * pady)

    def f(dr, s):
        dr.rounded_rectangle([0, 0, w * s, h * s], radius=h // 2 * s, fill=tuple(bg) + (255,),
                             outline=(tuple(outline) + (255,)) if outline else None, width=4 * s)
    im = ss((w, h), f, 3)
    ImageDraw.Draw(im).text((w / 2, h / 2 + 2), text, font=font, fill=fg, anchor='mm')
    return im


def card(w, h, fill=(255, 255, 255), r=36, outline=(225, 212, 185), shadow=True):
    def f(d, s):
        if shadow:
            d.rounded_rectangle([6 * s, 10 * s, (w - 2) * s, h * s], radius=r * s, fill=(65, 38, 24, 40))
        d.rounded_rectangle([0, 0, (w - 8) * s, (h - 10) * s], radius=r * s, fill=tuple(fill) + (255,),
                            outline=tuple(outline) + (255,), width=3 * s)
    return ss((w, h), f, 2)


def fit_image(im, w, h, r=28):
    """Cover-crop `im` into a w x h rounded rectangle."""
    im = im.convert('RGB')
    s = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    im = im.crop((x, y, x + w, y + h)).convert('RGBA')
    mask = ss((w, h), lambda d, s_: d.rounded_rectangle([0, 0, w * s_, h * s_], radius=r * s_, fill=(255, 255, 255, 255)), 2)
    im.putalpha(mask.getchannel('A'))
    return im


def check_icon(size, color):
    def f(d, s):
        w = size * s
        d.line([(w * .2, w * .52), (w * .42, w * .72), (w * .8, w * .28)], fill=tuple(color) + (255,), width=int(w * .14), joint='curve')
    return ss((size, size), f, 3)


def color_to_alpha(im):
    """White-background logo -> transparent PNG."""
    a = np.asarray(im.convert('RGB')).astype(np.float32)
    mn = a.min(axis=2)
    alpha = np.clip((255 - mn) / (255 - 60.0), 0, 1)
    alpha = np.where(mn > 240, 0, alpha)
    alpha = np.clip(alpha * 1.15, 0, 1)
    out = np.zeros(a.shape[:2] + (4,), np.float32)
    safe = np.maximum(alpha, 1e-3)[..., None]
    out[..., :3] = np.clip((a - 255 * (1 - safe)) / safe, 0, 255)
    out[..., 3] = alpha * 255
    return Image.fromarray(out.astype(np.uint8), 'RGBA')


def blur_shadow(sprite, color=(65, 38, 24, 55), radius=14):
    sh = Image.new('RGBA', sprite.size, (0, 0, 0, 0))
    sh.paste(color, (0, 0), sprite.getchannel('A'))
    return sh.filter(ImageFilter.GaussianBlur(radius))
