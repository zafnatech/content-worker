#!/usr/bin/env python3
"""Render ONE job:  python3 factory.py jobs/whatsapp-business.json [--preview 3,12,25] [--draft] [--out-dir out/2026-11-06]

Steps: load job -> consent check -> voices (cached / raw clips / ElevenLabs API) -> timeline -> render MP4 + SRT + manifest."""
import os
import sys
import json
import argparse
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

from cf.env import load_env         # noqa: E402
from cf.brand import Brand          # noqa: E402
from cf import guardrails          # noqa: E402
load_env()
from cf.timeline import Scene, build  # noqa: E402
from cf.voice import ensure_voice   # noqa: E402
from cf.render import Ctx, encode   # noqa: E402


def srt_time(x):
    h, m, s = int(x // 3600), int(x % 3600 // 60), x % 60
    return f"{h:02d}:{m:02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


def consent_ok(job):
    client = job.get('client')
    uses_client_media = any(str((s.get('visual') or {}).get('path', '')).startswith('clients/') for s in job['scenes'])
    if uses_client_media and not client:
        return False, 'el job usa archivos de clients/ pero no declara "client"'
    if not client:
        return True, 'sin cliente'
    try:
        raw = os.environ.get('CLIENTS_JSON')   # in the cloud the consent registry lives in the host's env, not in git
        if raw:
            reg = json.loads(raw)
        else:
            with open('clients.json', encoding='utf-8') as f:
                reg = json.load(f)
    except (OSError, ValueError):
        return False, 'no encuentro el registro de permisos (CLIENTS_JSON o clients.json)'
    c = reg.get(client)
    if not c:
        return False, f'cliente "{client}" no está en clients.json'
    if not c.get('video_consent'):
        return False, f'"{client}" no ha dado permiso de video (video_consent=false)'
    return True, f'permiso de {client} registrado ({c.get("consent_date")})'


def run(job_path, preview=None, draft=False, out_dir=None, force_voice_pending=True):
    with open(job_path, encoding='utf-8') as f:
        job = json.load(f)
    jid = job['id']
    ok, why = consent_ok(job)
    if not ok and not draft:
        print(f'[{jid}] BLOQUEADO: {why}. Usa --draft solo para verlo internamente (sale marcado BORRADOR).')
        return 3
    if not ok:
        print(f'[{jid}] aviso: {why}. Saldrá marcado BORRADOR.')
    hits = guardrails.check(job)
    if hits:
        print(f'[{jid}] BLOQUEADO por reglas de la marca (Brand Book): {", ".join(hits)}. Corrige el texto del job.')
        return 4
    brand = Brand(job.get('brand', 'dinidine'))
    scenes = [Scene(i, s) for i, s in enumerate(job['scenes'])]
    pending = ensure_voice(jid, scenes, brand, job.get('atempo'))
    total = build(scenes)
    if pending:
        print(f'[{jid}] voz pendiente en {len(pending)} escena(s) -> voz/{jid}/PENDIENTE.md (se usa duración estimada)')
    ctx = Ctx(brand, scenes, total, draft=(draft and not ok))
    if preview:
        encode(ctx, None, 'build', preview=[float(x) for x in preview.split(',')])
        print(f'[{jid}] total {total:.1f}s  inicios {[round(s.start, 1) for s in scenes]}')
        return 0
    out_dir = out_dir or os.path.join('out', datetime.date.today().isoformat())
    os.makedirs(out_dir, exist_ok=True)
    mp4 = os.path.join(out_dir, f'{jid}.mp4')
    encode(ctx, mp4, 'build')
    with open(os.path.join(out_dir, f'{jid}.srt'), 'w', encoding='utf-8') as f:
        n = 1
        for sc in scenes:
            for a, z, txt in sc.chunks:
                f.write(f'{n}\n{srt_time(a)} --> {srt_time(z)}\n{txt}\n\n')
                n += 1
    from cf.voice import say_text
    chars = sum(len(say_text(sc, brand)) for sc in scenes)
    price = {'eleven_v4': 0.08, 'eleven_v4_turbo': 0.04}.get(os.environ.get('ELEVENLABS_MODEL_ID') or 'eleven_v4_turbo')
    import re as _re
    hook = next((sc for sc in job['scenes'] if sc.get('type') == 'hook'), job['scenes'][0])
    title = job.get('title') or _re.sub(r'\*\*', '', hook.get('title', jid))
    manifest = {'id': jid, 'title': title[:100], 'voice_chars': chars,
                'voice_cost_usd_est': round(chars / 1000 * price, 4) if price else None,   # tarifa API por 1000 caracteres; sin regeneraciones
                'brand': brand.slug, 'client': job.get('client'), 'consent': why, 'draft': bool(draft and not ok),
                'duration_s': round(total, 1), 'voice': 'real' if not pending else 'PENDIENTE (sin voz en escenas: ' + ', '.join(s.id for s in pending) + ')',
                'caption': job.get('caption', ''), 'hashtags': job.get('hashtags', []), 'cta': job.get('cta_text', ''),
                'captions': job.get('captions', {}), 'titles': job.get('titles', {}), 'ai_disclosure': job.get('ai_disclosure', True),
                'verify_before_publish': job.get('verify', []), 'file': mp4}
    with open(os.path.join(out_dir, f'{jid}.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f'[{jid}] OK {mp4} {total:.1f}s')
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('job')
    ap.add_argument('--preview')
    ap.add_argument('--draft', action='store_true')
    ap.add_argument('--out-dir')
    a = ap.parse_args()
    sys.exit(run(a.job, a.preview, a.draft, a.out_dir))
