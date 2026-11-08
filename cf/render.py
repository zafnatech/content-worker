"""Compose frames and encode. Frame function -> raw RGB -> ffmpeg (libx264 crf 18, faststart), plus voices + music."""
import os
import subprocess
from PIL import Image, ImageDraw
from .draw import W, H, FPS, sm
from .templates import TYPES
from .avatar import Avatar
from .music import make_music
from .timeline import master_envelope


class Ctx:
    def __init__(self, brand, scenes, total, draft=False):
        self.brand, self.scenes, self.total, self.draft = brand, scenes, total, draft
        self.cache = {}
        self.bg = brand.background()
        env, hop = master_envelope(scenes, total)
        self.avatar = Avatar(brand, scenes, env, hop)

    def scene_at(self, t):
        i = 0
        for k, sc in enumerate(self.scenes):
            if sc.start <= t + 1e-9:
                i = k
        return i


def subtitles(ctx, base, t):
    b = ctx.brand
    for sc in ctx.scenes:
        for a, z, txt in sc.chunks:
            if a <= t < z + 0.05:
                d = ImageDraw.Draw(base)
                fnt = b.font('display', 60)
                words, lines, cur = txt.split(), [], ''
                for w_ in words:
                    tt = (cur + ' ' + w_).strip()
                    if d.textlength(tt, font=fnt) > 920 and cur:
                        lines.append(cur)
                        cur = w_
                    else:
                        cur = tt
                lines.append(cur)
                lh, ph_ = 82, 82 * len(lines) + 44
                y1 = 1440
                y0 = y1 - ph_
                pw = max(d.textlength(l, font=fnt) for l in lines) + 80
                fade = max(0.0, min(1, (t - a) / 0.12, (z + 0.05 - t) / 0.1 if z - t < 0.1 else 1))
                plate = Image.new('RGBA', (int(pw), ph_), (0, 0, 0, 0))
                ImageDraw.Draw(plate).rounded_rectangle([0, 0, pw, ph_], radius=34, fill=b.INK + (int(235 * fade),))
                base.paste(plate, (int((W - pw) / 2), y0), plate)
                for i, l in enumerate(lines):
                    x = (W - d.textlength(l, font=fnt)) / 2
                    for w_ in l.split(' '):
                        hl = any(h in w_ for h in b.highlight)
                        d.text((x, y0 + 22 + i * lh), w_, font=fnt, fill=b.ACC if hl else b.WHITE)
                        x += d.textlength(w_ + ' ', font=fnt)
                return


def frame(ctx, t):
    base = ctx.bg.copy()
    i = ctx.scene_at(t)
    sc = ctx.scenes[i]
    TYPES[sc.type](ctx, base, sc, t - sc.start)
    ts = t - sc.start
    if ts < 0.25 and i > 0:
        pv = ctx.scenes[i - 1]
        prev = ctx.bg.copy()
        TYPES[pv.type](ctx, prev, pv, pv.dur - 0.01)
        base = Image.blend(prev, base, sm(ts / 0.25))
    ctx.avatar.draw(base, t, i)
    subtitles(ctx, base, t)
    if ctx.draft:
        d = ImageDraw.Draw(base)
        d.rounded_rectangle([640, 60, 1030, 120], radius=30, fill=(190, 60, 40))
        d.text((835, 90), 'BORRADOR · NO PUBLICAR', font=ctx.brand.font('body', 26), fill=(255, 255, 255), anchor='mm')
    f = min(1, t / 0.3, (ctx.total - t) / 0.5)
    if f < 1:
        base = Image.blend(Image.new('RGB', (W, H), ctx.brand.BG), base, max(0, f))
    return base


def encode(ctx, out_path, build_dir, preview=None):
    os.makedirs(build_dir, exist_ok=True)
    if preview:
        for t in preview:
            frame(ctx, t).save(os.path.join(build_dir, f'prev_{t:05.1f}.png'))
        return None
    mus = os.path.join(build_dir, 'musica.wav')
    make_music(mus, ctx.total + 0.2, ctx.brand.bpm)
    tmp = out_path.replace('.mp4', '.video.tmp.mp4')
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
           '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(round(ctx.total * FPS))
    for i in range(n):
        p.stdin.write(frame(ctx, i / FPS).tobytes())
    p.stdin.close()
    assert p.wait() == 0, 'ffmpeg video encode failed'
    voices = [sc for sc in ctx.scenes if sc.voice_path]
    ins = ['-i', tmp, '-i', mus]
    for sc in voices:
        ins += ['-i', sc.voice_path]
    if voices:
        fc = '[1:a]volume=0.22[m];' + ''.join(f'[{k + 2}:a]adelay={int(sc.start * 1000)}|{int(sc.start * 1000)}[v{k}];' for k, sc in enumerate(voices))
        fc += '[m]' + ''.join(f'[v{k}]' for k in range(len(voices))) + f'amix=inputs={len(voices) + 1}:normalize=0:duration=first[a]'
    else:
        fc = '[1:a]volume=0.8[a]'
    out_tmp = out_path.replace('.mp4', '.tmp.mp4')
    subprocess.check_call(['ffmpeg', '-y', '-loglevel', 'error', *ins, '-filter_complex', fc, '-map', '0:v', '-map', '[a]', '-c:v', 'copy',
                           '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', out_tmp])
    os.replace(out_tmp, out_path)
    os.remove(tmp)
    return out_path
