"""The mascot (Dini). Moves between scene-specific spots and 'talks': the voice loudness drives a squash/hop,
so it reads as speaking without needing a mouth rig. Replace later by a real animated avatar without touching templates."""
import math
from PIL import Image
from .draw import sm, paste, blur_shadow

# default spot per scene type: (center x, center y, height)
SPOTS = {'hook': (540, 1040, 450), 'step': (905, 1690, 300), 'outro': (540, 1170, 470)}


class Avatar:
    def __init__(self, brand, scenes, env, hop):
        self.b, self.scenes, self.env, self.hop = brand, scenes, env, hop

    def spot(self, sc):
        b = sc.data.get('bee', None)
        if b is False:
            return None
        if isinstance(b, list) and len(b) == 3:
            return tuple(b)
        return SPOTS.get(sc.type, SPOTS['step'])

    def pose(self, t, i):
        sc = self.scenes[i]
        cur = self.spot(sc)
        prev = self.spot(self.scenes[i - 1]) if i > 0 else None
        if cur is None:
            return None
        if prev is None:
            prev = (cur[0] + (600 if i == 0 else 0), cur[1], cur[2])
        u = sm((t - sc.start) / 0.6)
        return tuple(prev[k] + (cur[k] - prev[k]) * u for k in range(3))

    def level(self, t):
        i = int(t / self.hop)
        return float(self.env[min(max(i, 0), len(self.env) - 1)])

    def draw(self, base, t, i):
        if self.b.mascot is None:
            return
        p = self.pose(t, i)
        if p is None:
            return
        cx, cy, hh = p
        e = self.level(t)
        cy += math.sin(t * 3.2) * 10 - 16 * e
        cx += math.sin(t * 1.7) * 8
        m = self.b.mascot
        s = hh / m.height
        w, h = int(m.width * s * (1 - 0.03 * e)), int(m.height * s * (1 + 0.035 * math.sin(t * 36) + 0.06 * e))
        sprite = m.resize((w, h), Image.LANCZOS).rotate(math.sin(t * 2.1) * 4 + e * 3 * math.sin(t * 13), resample=Image.BICUBIC, expand=True)
        paste(base, blur_shadow(sprite), cx - sprite.width / 2 + 10, cy - sprite.height / 2 + 26)
        paste(base, sprite, cx - sprite.width / 2, cy - sprite.height / 2)
