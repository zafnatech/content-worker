"""A brand = brands/<slug>/brand.json + assets. Add a folder to add a brand (Tarsiz, Ferritico, ...)."""
import os
import json
from PIL import Image, ImageDraw, ImageFont
from .draw import W, H, color_to_alpha

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Brand:
    def __init__(self, slug):
        self.slug = slug
        self.dir = os.path.join(ROOT, 'brands', slug)
        with open(os.path.join(self.dir, 'brand.json'), encoding='utf-8') as f:
            self.cfg = json.load(f)
        p = self.cfg['palette']
        self.BG, self.INK, self.ACC = tuple(p['bg']), tuple(p['ink']), tuple(p['accent'])
        self.WHITE, self.OK = tuple(p.get('white', (255, 255, 255))), tuple(p.get('ok', (46, 125, 50)))
        self.highlight = self.cfg.get('subtitle_highlight', [])
        self.voice_cfg = self.cfg.get('voice', {})
        self.bpm = self.cfg.get('music', {}).get('bpm', 88)
        self._fonts = self.cfg['fonts']
        self.mascot = None
        if self.cfg.get('mascot'):
            m = Image.open(os.path.join(self.dir, self.cfg['mascot'])).convert('RGBA')
            self.mascot = m.crop(m.getbbox())
        self.logo = None
        if self.cfg.get('logo'):
            lg = Image.open(os.path.join(self.dir, self.cfg['logo'])).convert('RGB')
            if self.cfg.get('logo_crop'):
                lg = lg.crop(tuple(self.cfg['logo_crop']))
            self.logo = color_to_alpha(lg) if self.cfg.get('logo_white_bg') else lg.convert('RGBA')

    def font(self, role, size):
        return ImageFont.truetype(os.path.join(ROOT, 'fonts', self._fonts[role]), size)

    def background(self):
        ov = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        a = self.ACC
        d.ellipse([560, -300, 1400, 540], fill=a + (46,))
        d.ellipse([-420, 1300, 520, 2240], fill=a + (38,))
        d.ellipse([-260, -220, 300, 330], fill=self.INK + (16,))
        return Image.alpha_composite(Image.new('RGBA', (W, H), self.BG + (255,)), ov).convert('RGB')

    def logo_on(self, base, x, y, w):
        if self.logo is None:
            return
        lg = self.logo.resize((w, int(self.logo.height * w / self.logo.width)), Image.LANCZOS)
        base.paste(lg, (x, y), lg)
