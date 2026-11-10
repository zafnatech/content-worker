"""Original background music, synthesized (no licensing): soft pad + kalimba plucks, I-vi-IV-V in C."""
import wave
import numpy as np


def make_music(path, dur, bpm=88, sr=44100):
    n = int(dur * sr)
    t = np.arange(n) / sr
    out = np.zeros(n, dtype=np.float64)
    beat = 60 / bpm
    bar = 4 * beat
    chords = [[48, 55, 59, 64], [45, 52, 60, 64], [41, 48, 57, 64], [43, 50, 59, 62]]  # Cmaj7 Am7 Fmaj7 G6
    fr = lambda m: 440 * 2 ** ((m - 69) / 12)
    for b in range(int(dur / bar) + 1):
        ch = chords[b % 4]
        s0 = int(b * bar * sr)
        if s0 >= n:
            break
        e = min(n, s0 + int(bar * sr * 1.15))
        tt = np.arange(e - s0) / sr
        env = np.minimum(1, tt / 0.5) * np.exp(-np.maximum(0, tt - bar * 0.9) * 3)
        pad = sum(np.sin(2 * np.pi * fr(m) * tt) + 0.5 * np.sin(2 * np.pi * fr(m) * 1.004 * tt) for m in ch[1:]) * 0.035
        bass = np.sin(2 * np.pi * fr(ch[0] - 12) * tt) * 0.10 * np.minimum(1, tt / 0.05) * np.exp(-tt * 0.9)
        out[s0:e] += (pad * env + bass)[:e - s0]
        arp = [ch[1] + 12, ch[2] + 12, ch[3] + 12, ch[2] + 12]
        for k in range(8):
            m = arp[k % 4] + (12 if k == 7 else 0)
            ps = s0 + int((k * beat / 2) * sr)
            if ps >= n:
                break
            pl = min(n - ps, int(0.7 * sr))
            tp = np.arange(pl) / sr
            out[ps:ps + pl] += (np.sin(2 * np.pi * fr(m) * tp) + 0.3 * np.sin(2 * np.pi * fr(m) * 2 * tp)) * np.exp(-tp * 7) * 0.07
    out *= np.minimum(1, t / 1.5) * np.minimum(1, (dur - t) / 2.0)
    out = out / np.max(np.abs(out)) * 0.55
    st = np.stack([out, np.roll(out, int(0.012 * sr))], 1)
    with wave.open(path, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((st * 32767).astype('<i2').tobytes())


# ---------------------------------------------------------------------------------------------------------------
# Style presets for short clips (original, synthesized: no licensing). One style per day so two pieces in a row
# never share a "song". make_music() above stays as the kalimba pad used by the talking-mascot videos.
STYLES = ['cumbia', 'lofi', 'urbano', 'bright']
_SR = 44100


def style_for(date_ordinal, avoid=None):
    """Rotates by date; never returns `avoid` (the previous piece's style)."""
    s = STYLES[date_ordinal % len(STYLES)]
    if avoid and s == avoid:
        s = STYLES[(date_ordinal + 1) % len(STYLES)]
    return s


def _fr(m):
    return 440 * 2 ** ((m - 69) / 12)


def _add(out, start, sig, gain=1.0):
    i = int(start * _SR)
    if i >= len(out):
        return
    j = min(len(out), i + len(sig))
    out[i:j] += sig[:j - i] * gain


def _kick(rng, length=0.28):
    t = np.arange(int(length * _SR)) / _SR
    f = 45 + 95 * np.exp(-t * 28)
    return np.sin(2 * np.pi * np.cumsum(f) / _SR) * np.exp(-t * 11) * 0.9


def _noise_hit(rng, length, decay, hp=True):
    n = rng.standard_normal(int(length * _SR))
    if hp:
        n = n - np.concatenate([[0], n[:-1]]) * 0.97   # crude high-pass
    t = np.arange(len(n)) / _SR
    return n * np.exp(-t * decay) * 0.35


def _clap(rng):
    h = _noise_hit(rng, 0.22, 20)
    t = np.arange(len(h)) / _SR
    return h * 1.2 + np.sin(2 * np.pi * 190 * t) * np.exp(-t * 25) * 0.25


def _pluck(m, length=0.5, decay=7, bright=0.3):
    t = np.arange(int(length * _SR)) / _SR
    f = _fr(m)
    return (np.sin(2 * np.pi * f * t) + bright * np.sin(2 * np.pi * f * 2 * t) + 0.12 * np.sin(2 * np.pi * f * 3 * t)) * np.exp(-t * decay)


def _bass(m, length=0.4, decay=4):
    t = np.arange(int(length * _SR)) / _SR
    f = _fr(m)
    w = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * f * 2 * t)
    return w * np.minimum(1, t / 0.01) * np.exp(-t * decay)


def _keys(m, length, tremolo=5.0):
    t = np.arange(int(length * _SR)) / _SR
    f = _fr(m)
    w = np.sin(2 * np.pi * f * t) + 0.45 * np.sin(2 * np.pi * f * 2 * t) * np.exp(-t * 3) + 0.2 * np.sin(2 * np.pi * f * 4 * t) * np.exp(-t * 8)
    return w * (0.85 + 0.15 * np.sin(2 * np.pi * tremolo * t)) * np.minimum(1, t / 0.01) * np.exp(-t * 1.6)


def make_preset(path, dur, style, seed=0):
    """Writes a stereo WAV of `dur` seconds in one of STYLES. Deterministic for (style, seed)."""
    rng = np.random.default_rng(seed)
    n = int(dur * _SR)
    out = np.zeros(n)
    if style == 'cumbia':      # Am Dm E Am, guiro 8ths, bass on 1/3, offbeat organ stabs
        bpm, prog = 94, [(57, [69, 72, 76]), (50, [65, 69, 74]), (52, [68, 71, 76]), (57, [69, 72, 76])]
        beat = 60 / bpm
        for b in range(int(dur / (4 * beat)) + 2):
            root, ch = prog[b % 4]
            t0 = b * 4 * beat
            for k in range(8):
                g = 0.9 if k % 2 == 0 else 0.5
                _add(out, t0 + k * beat / 2, _noise_hit(rng, 0.08, 45), g * 0.6)
            for k in (0, 2):
                _add(out, t0 + k * beat, _bass(root - 12, 0.5, 5), 0.5)
            _add(out, t0, _kick(rng), 0.55)
            _add(out, t0 + 2 * beat, _kick(rng), 0.55)
            _add(out, t0 + 1 * beat, _clap(rng), 0.35)
            _add(out, t0 + 3 * beat, _clap(rng), 0.35)
            _add(out, t0 + 2.5 * beat, _bass(root - 12 + 7, 0.25, 8), 0.4)
            for k in range(4):
                for m in ch:
                    _add(out, t0 + k * beat + beat / 2, _pluck(m, 0.22, 14, 0.7), 0.11)
    elif style == 'lofi':      # Dm9 G13 Cmaj7 Am7, soft swung drums, warm keys
        bpm, prog = 78, [(50, [62, 65, 69, 72]), (55, [65, 69, 71, 76]), (48, [64, 67, 71, 74]), (57, [64, 67, 72, 76])]
        beat = 60 / bpm
        for b in range(int(dur / (4 * beat)) + 2):
            root, ch = prog[b % 4]
            t0 = b * 4 * beat
            for m in ch:
                _add(out, t0, _keys(m, 4 * beat * 1.05), 0.075)
            _add(out, t0, _bass(root - 12, 1.4, 1.8), 0.6)
            _add(out, t0 + 2.5 * beat, _bass(root - 12, 0.8, 3), 0.4)
            for k in (0, 2.5):
                _add(out, t0 + k * beat, _kick(rng), 0.6)
            for k in (1, 3):
                _add(out, t0 + k * beat, _clap(rng), 0.28)
            for k in range(8):
                sw = beat / 2 * (1.18 if k % 2 else 1)
                _add(out, t0 + (k // 2) * beat + (sw if k % 2 else 0), _noise_hit(rng, 0.06, 55), 0.3)
            _add(out, t0 + 3.5 * beat, _pluck(ch[3] + 12, 0.6, 5, 0.2), 0.08)
    elif style == 'urbano':    # dembow, Am F C G, sub bass + short lead
        bpm, prog = 96, [(45, [69, 72, 76]), (41, [65, 69, 72]), (48, [67, 72, 76]), (43, [67, 71, 74])]
        beat = 60 / bpm
        lead = [0, 2, 0, 1, 2, 1, 0, 2]
        for b in range(int(dur / (4 * beat)) + 2):
            root, ch = prog[b % 4]
            t0 = b * 4 * beat
            for k in range(4):
                _add(out, t0 + k * beat, _kick(rng), 0.6)
            for k in (0.75, 1.5, 2.75, 3.5):   # dembow snare pattern
                _add(out, t0 + k * beat, _clap(rng), 0.32)
            for k in range(8):
                _add(out, t0 + k * beat / 2, _noise_hit(rng, 0.04, 80), 0.22)
            for k, off in ((0, 0), (1.5, 0), (2, 0), (3.5, 7)):
                _add(out, t0 + k * beat, _bass(root - 12 + off, 0.45, 5), 0.55)
            for i, idx in enumerate(lead):
                _add(out, t0 + i * beat / 2, _pluck(ch[idx] + 12, 0.28, 12, 0.6), 0.10)
    else:                      # 'bright': C G Am F, four-on-floor, offbeat hats, arp
        bpm, prog = 112, [(48, [60, 64, 67]), (43, [59, 62, 67]), (45, [60, 64, 69]), (41, [60, 65, 69])]
        beat = 60 / bpm
        for b in range(int(dur / (4 * beat)) + 2):
            root, ch = prog[b % 4]
            t0 = b * 4 * beat
            for k in range(4):
                _add(out, t0 + k * beat, _kick(rng), 0.5)
                _add(out, t0 + k * beat + beat / 2, _noise_hit(rng, 0.05, 70), 0.3)
            for k in (1, 3):
                _add(out, t0 + k * beat, _clap(rng), 0.3)
            for k in range(8):
                _add(out, t0 + k * beat / 2, _bass(root - 12 if k % 2 == 0 else root - 12 + 12, 0.22, 9), 0.4)
            for k in range(16):
                _add(out, t0 + k * beat / 4, _pluck(ch[k % 3] + 12 + (12 if k % 7 == 6 else 0), 0.2, 16, 0.5), 0.07)
    t = np.arange(n) / _SR
    out *= np.minimum(1, t / 0.4) * np.minimum(1, np.maximum(0, (dur - t)) / 1.2)
    peak = np.max(np.abs(out)) or 1.0
    out = out / peak * 0.6
    st = np.stack([out, np.roll(out, int(0.008 * _SR))], 1)
    with wave.open(path, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(_SR)
        w.writeframes((st * 32767).astype('<i2').tobytes())
