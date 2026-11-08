"""Job JSON -> scenes with timing, auto subtitle chunks and mascot envelope."""
import re
import numpy as np

WPS = 2.7        # estimated words/second of the voice AFTER speed-up (only used when no clip exists yet)
PAUSE = 0.30     # breath between scenes
MIN_SCENE = 2.2  # a scene never lasts less than this
TAIL = 0.6


class Scene:
    def __init__(self, idx, d):
        self.idx = idx
        self.id = d.get('id') or f's{idx + 1}'
        self.type = d.get('type', 'step')
        self.data = d
        self.speak = d['speak'].strip()
        self.say = d.get('say')
        self.voice_path = None
        self.voice_dur = None
        self.start = 0.0
        self.dur = 0.0
        self.chunks = []  # (t0, t1, text) absolute seconds


def split_chunks(text, maxlen=34):
    """Subtitle phrases: break at punctuation, merge short ones, never longer than ~maxlen chars."""
    pieces = [p.strip() for p in re.split(r'(?<=[.,;:?!])\s+', text) if p.strip()]
    out, cur = [], ''
    for p in pieces:
        if cur and len(cur) + 1 + len(p) <= maxlen:
            cur += ' ' + p
        else:
            if cur:
                out.append(cur)
            cur = p
    if cur:
        out.append(cur)
    final = []
    for c in out:
        if len(c) <= maxlen + 8:
            final.append(c)
            continue
        words, cur = c.split(), ''
        n = -(-len(c) // maxlen)
        target = len(c) / n
        for w in words:
            if cur and len(cur) + 1 + len(w) > target + 6:
                final.append(cur)
                cur = w
            else:
                cur = (cur + ' ' + w).strip()
        if cur:
            final.append(cur)
    return final


def build(scenes):
    t = 0.0
    for sc in scenes:
        voice = sc.voice_dur if sc.voice_dur else len(sc.speak.split()) / WPS
        sc.voice = voice
        sc.dur = max(MIN_SCENE, voice + PAUSE)
        sc.start = t
        chunks = split_chunks(sc.speak)
        wts = [max(len(c), 1) for c in chunks]
        x = sc.start
        sc.chunks = []
        for c, w in zip(chunks, wts):
            d = voice * w / sum(wts)
            sc.chunks.append((x, x + d, c))
            x += d
        t += sc.dur
    total = t + TAIL
    return total


def master_envelope(scenes, total, hop=0.02):
    from .voice import envelope
    n = int(total / hop) + 2
    env = np.zeros(n, dtype='float32')
    for sc in scenes:
        if sc.voice_path:
            e, h = envelope(sc.voice_path, hop=hop)
            i0 = int(sc.start / hop)
            m = min(len(e), n - i0)
            env[i0:i0 + m] = e[:m]
    # light smoothing so the mascot doesn't jitter
    k = np.array([.25, .5, .25], dtype='float32')
    return np.convolve(env, k, mode='same'), hop
