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
