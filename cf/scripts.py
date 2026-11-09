"""Script bank -> job. Pure functions.

brands/<slug>/scripts.json is a list of pre-written pieces (tips, product, objections, brand, special dates). Nothing is
invented at run time: every claim in the bank was written against the project's "what exists today" list and is reviewed
once by Jonathan. A piece only renders when it is approved and every gate in `needs` is unlocked.

  approved  false until Jonathan says yes (or WORKER_BANK_APPROVED=1 in the host dashboard approves the whole bank)
  needs     gates for claims that are not confirmed yet, e.g. ["tv"], ["agents"]; unlocked with WORKER_UNLOCK=tv,agents
  on        ISO date for special-date pieces (they are picked by date, not by rotation)
"""
import os
import re
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_bank(brand):
    path = os.path.join(ROOT, 'brands', brand, 'scripts.json')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def unlocked():
    return {x.strip().lower() for x in os.environ.get('WORKER_UNLOCK', '').split(',') if x.strip()}


def usable(s, gates=None):
    gates = unlocked() if gates is None else gates
    ok = bool(s.get('approved')) or os.environ.get('WORKER_BANK_APPROVED', '0') == '1'
    return ok and set(s.get('needs') or []) <= gates


def pool(bank, pillar, gates=None):
    """Rotation pool of a pillar: usable pieces without a fixed date, in file order (stable)."""
    return [s for s in bank if s.get('pillar') == pillar and not s.get('on') and usable(s, gates)]


def by_id(bank, sid, gates=None):
    s = next((x for x in bank if x.get('id') == sid), None)
    return s if s and usable(s, gates) else None


def plain(text):
    return re.sub(r'\*\*', '', str(text))


def build_job(s, date, brand='dinidine', schedule=None):
    d = date.isoformat()
    jid = f'{s["id"]}-{d}'[:80]
    hook = s['hook']
    scenes = [
        {'type': 'hook', 'kicker': s.get('kicker', ''), 'title': hook, 'speak': s.get('hook_speak') or plain(hook)},
        {'type': 'step', 'title': s['body_title'], 'speak': s['speak_body'], 'points': s['points']},
        {'type': 'outro', 'title': s['outro_title'], 'cta': s['cta'], 'speak': s['speak_outro']},
    ]
    return {
        'id': jid, 'brand': brand, 'template': 'tutorial', 'client': None, 'title': plain(hook)[:100],
        'caption': s['caption'], 'hashtags': s.get('hashtags') or ['#restaurantes', '#menudigital', '#negociolatino'],
        'cta_text': s['cta'], 'ai_disclosure': False, 'schedule': schedule or None,
        'verify': list(s.get('verify') or []) + [f'Pieza del banco de guiones ({s["id"]}), programada para {d}.'],
        'scenes': scenes,
    }
