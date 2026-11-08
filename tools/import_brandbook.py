#!/usr/bin/env python3
"""Builds brands/<slug>/ (brand.json + assets) for every product brand from the brand-book delivery.

  python3 tools/import_brandbook.py <folder with BRAND-BOOK.md and assets/> [--only slug,...]

Reads: BRAND-BOOK.md (status, language, honest message, traits, voice, avoid, working palette, landing) and the
transparent mascot PNGs. An existing brands/<slug>/brand.json is MERGED (its palette, fonts, voice, music are kept and
only the guardrails are refreshed), so the approved DiniDine look is never overwritten.
Palettes come from the brief's "paleta de trabajo" and are marked provisional until the logo HEX are normalised.
"""
import os, re, sys, json, argparse
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIELDS = {'Posicionamiento': 'positioning', 'Mensaje honesto': 'honest_message', 'Rasgos canónicos': 'canonical_traits',
          'Voz': 'voice_style', 'Evitar': 'avoid', 'Frase editorial de ejemplo (no eslogan aprobado)': 'sample_line_not_approved'}
MASCOT_PREFERENCE = ['10-cuerpo-transparente.png', '01-PoniPro-cuerpo-1024.png']


def lum(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def hex_rgb(h):
    h = h.lstrip('#')
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def mix(rgb, white, k):
    return [round(c * (1 - k) + white * k) for c in rgb]


def parse(md):
    brands = {}
    for block in re.split(r'\n### ', md.split('\n## Marcas', 1)[1].split('\n## Decisiones', 1)[0])[1:]:
        name, _, body = block.partition('\n')
        name = name.strip()
        d = {'name': name}
        m = re.search(r'Animal: (.+?)\. Sector: (.+?)\. Idioma: (\w+)\. Estado público: (.+?)\.', body)
        d.update(animal=m.group(1), sector=m.group(2), language=m.group(3).lower(), public_status=m.group(4))
        for line in body.splitlines():
            for label, key in FIELDS.items():
                if line.startswith(f'- {label}:'):
                    d[key] = line.split(':', 1)[1].strip()
        pal = re.search(r'`(#[0-9A-Fa-f]{6})` y `(#[0-9A-Fa-f]{6})`', body)
        d['working_palette'] = [pal.group(1), pal.group(2)]
        d['landing'] = re.search(r'Landing: (\S+)', body).group(1)
        brands[name.lower()] = d
    return brands


def build(slug, info, src, force_assets=True):
    bdir = os.path.join(ROOT, 'brands', slug)
    os.makedirs(os.path.join(bdir, 'assets'), exist_ok=True)
    cfg_path = os.path.join(bdir, 'brand.json')
    cfg = json.load(open(cfg_path, encoding='utf-8')) if os.path.exists(cfg_path) else {}
    cfg.setdefault('id', slug)
    cfg.setdefault('name', info['name'])
    a, b = sorted(info['working_palette'], key=lambda h: lum(hex_rgb(h)))   # darker = ink, lighter = accent
    if 'palette' not in cfg:
        ink, acc = hex_rgb(a), hex_rgb(b)
        cfg['palette'] = {'bg': mix(acc, 255, 0.9), 'ink': ink, 'accent': acc, 'white': [255, 255, 255], 'ok': [46, 125, 50]}
        cfg['palette_status'] = 'provisional: from the brief; normalise against the approved logo'
    cfg.setdefault('fonts', {'display': 'Outfit-800.ttf', 'body': 'Outfit-700.ttf', 'soft': 'Outfit-600.ttf', 'condensed': 'Bebas.ttf'})
    cfg.setdefault('music', {'bpm': 88})
    cfg.setdefault('voice', {})   # ElevenLabs voice per brand: decided by Jonathan, not guessed
    adir = os.path.join(src, 'assets', info['name'])
    if 'mascot' not in cfg:
        pick = next((f for f in MASCOT_PREFERENCE if os.path.exists(os.path.join(adir, f))), None)
        if pick:
            im = Image.open(os.path.join(adir, pick)).convert('RGBA')
            im = im.crop(im.getbbox())
            im.thumbnail((1000, 1000), Image.LANCZOS)
            im.save(os.path.join(bdir, 'assets', 'mascot.png'), optimize=True)
            cfg['mascot'] = 'assets/mascot.png'
    if 'logo' not in cfg and os.path.exists(os.path.join(adir, 'logo.webp')):
        Image.open(os.path.join(adir, 'logo.webp')).convert('RGB').save(os.path.join(bdir, 'assets', 'logo.png'), optimize=True)
        cfg['logo'] = 'assets/logo.png'
        cfg['logo_white_bg'] = True
    cfg['guardrails'] = {k: info[k] for k in ('animal', 'sector', 'language', 'public_status', 'positioning', 'honest_message',
                                              'canonical_traits', 'voice_style', 'avoid', 'sample_line_not_approved', 'landing') if k in info}
    cfg['guardrails']['source'] = 'Zafnatech Brand Book 2026-11-07'
    json.dump(cfg, open(cfg_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return cfg


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('--only')
    args = ap.parse_args()
    brands = parse(open(os.path.join(args.src, 'BRAND-BOOK.md'), encoding='utf-8').read())
    only = set(args.only.split(',')) if args.only else None
    for slug, info in brands.items():
        if only and slug not in only:
            continue
        build(slug, info, args.src)
        print('ok', slug, info['public_status'], info['language'])
