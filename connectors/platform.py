"""READ-ONLY connector to the DiniDine platform (Agent API, scope `menu:read`).

Pulls a restaurant's menu so a template can show real dishes/prices. Uses ONLY GET endpoints; it cannot change anything.
Env (never in code or chat):  DINIDINE_API_URL (brand admin host, e.g. https://...)  DINIDINE_API_KEY (zk_..., menu:read only)

  python3 connectors/platform.py businesses
  python3 connectors/platform.py menu <slug>  > clients/<slug>/menu.json

Spec: zafnatech-platform/docs/AGENT_API.md. NOT tested from the cloud sandbox (its network cannot reach the platform):
run it on your Mac or a server with the env vars set. Using a restaurant's data in a published video still requires
video_consent=true in clients.json.
"""
import os
import sys
import json
import urllib.request


def get(path):
    base, key = os.environ.get('DINIDINE_API_URL'), os.environ.get('DINIDINE_API_KEY')
    if not (base and key):
        sys.exit('Faltan DINIDINE_API_URL y DINIDINE_API_KEY (llave con scope menu:read).')
    req = urllib.request.Request(base.rstrip('/') + '/api/agent/v1' + path, headers={'Authorization': f'Bearer {key}'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'businesses':
        print(json.dumps(get('/businesses'), ensure_ascii=False, indent=1))
    elif len(sys.argv) >= 3 and sys.argv[1] == 'menu':
        print(json.dumps(get(f'/businesses/{sys.argv[2]}/menu'), ensure_ascii=False, indent=1))
    else:
        sys.exit(__doc__)
