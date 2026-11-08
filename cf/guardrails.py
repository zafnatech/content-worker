"""Brand guardrails: phrases a brand's videos must never contain (Brand Book "evitar" / "mensaje honesto").
brands/<slug>/brand.json -> "banned_phrases": ["pedidos nativos", ...]. Matching ignores case and accents.
A hit blocks the render: fix the job text, do not bypass."""
import os
import json
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _norm(s):
    return unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().lower()


def _texts(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            if k in ('verify', 'id', 'brand', 'client', 'template'):   # internal notes are not published text
                continue
            yield from _texts(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _texts(v)


def banned_for(brand_slug):
    path = os.path.join(ROOT, 'brands', brand_slug, 'brand.json')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f).get('banned_phrases', [])


def check(job, brand_slug=None):
    """Banned phrases found in the job's public text (empty list = clean)."""
    phrases = banned_for(brand_slug or job.get('brand', 'dinidine'))
    blob = _norm(' '.join(_texts(job)))
    return [p for p in phrases if _norm(p) in blob]
