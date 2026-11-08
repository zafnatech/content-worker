"""Run:  python3 -m unittest tests.test_publisher -v   (uses a fake Postiz server on localhost; touches no network)."""
import os
import sys
import json
import tempfile
import threading
import unittest
import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ['PUBLISH_DB'] = os.path.join(TMP, 'q.db')
os.environ['POSTIZ_API_KEY'] = 'test-key'
sys.path.insert(0, HERE)
import publish  # noqa: E402
from publisher import store, plan, postiz  # noqa: E402

CALLS = []


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(n)
        CALLS.append((self.path, self.headers.get('Authorization'), self.headers.get('Content-Type'), body))
        if self.path.endswith('/upload'):
            out = {'id': 'vid-1', 'path': 'https://up.example/vid.mp4'}
        else:
            j = json.loads(body)
            out = [{'postId': f'p{i}', 'integration': p['integration']['id']} for i, p in enumerate(j['posts'])]
        b = json.dumps(out).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)


def manifest(name, **kw):
    mp4 = os.path.join(TMP, name + '.mp4')
    open(mp4, 'wb').write(b'\x00\x00fakevideo')
    m = {'id': name, 'title': 'Titulo ' + name, 'brand': 'dinidine', 'draft': False, 'voice': 'real', 'caption': 'Hola',
         'hashtags': ['#a', '#b'], 'verify_before_publish': [], 'file': mp4}
    m.update(kw)
    p = os.path.join(TMP, name + '.json')
    json.dump(m, open(p, 'w'))
    return p


def cfg(**kw):
    c = {'timezone': 'America/New_York', 'approval': 'if_verify', 'channels': [
        {'key': 'ig', 'brand': 'dinidine', 'network': 'instagram', 'integration_id': 'I1', 'enabled': True, 'daily_cap': 2, 'slots': ['12:30', '19:00']},
        {'key': 'tt', 'brand': 'dinidine', 'network': 'tiktok', 'integration_id': 'T1', 'enabled': True, 'daily_cap': 1, 'slots': ['13:00']},
        {'key': 'yt', 'brand': 'dinidine', 'network': 'youtube', 'integration_id': 'Y1', 'enabled': True, 'daily_cap': 1, 'slots': ['14:00']}]}
    c.update(kw)
    return c


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(('127.0.0.1', 0), Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        os.environ['POSTIZ_API_URL'] = f'http://127.0.0.1:{cls.srv.server_port}/api/public/v1'

    def setUp(self):
        if os.path.exists(store.DB):
            os.remove(store.DB)
        CALLS.clear()

    def test_refuses_draft_and_silent(self):
        self.assertFalse(plan.enqueue(manifest('d1', draft=True), cfg())[0])
        self.assertFalse(plan.enqueue(manifest('d2', voice='PENDIENTE (sin voz en escenas: x)'), cfg())[0])
        self.assertEqual(store.rows(), [])

    def test_verify_items_wait_for_approval(self):
        c = cfg()
        ok, _ = plan.enqueue(manifest('v1', verify_before_publish=['confirma X']), c)
        self.assertTrue(ok)
        self.assertEqual({r['status'] for r in store.rows()}, {'needs_review'})
        self.assertTrue(all(r['scheduled_at'] is None for r in store.rows()))
        self.assertEqual(plan.approve('v1', c), 3)
        self.assertEqual({r['status'] for r in store.rows()}, {'queued'})

    def test_daily_cap_and_distinct_slots(self):
        c = cfg()
        for i in range(4):
            plan.enqueue(manifest(f'c{i}'), c)
        ig = [r for r in store.rows('channel="ig"')]
        self.assertEqual(len({r['scheduled_at'] for r in ig}), 4)               # never two on the same slot
        tz = plan.ZoneInfo('America/New_York')
        per_day = {}
        for r in ig:
            d = datetime.datetime.strptime(r['scheduled_at'][:16], '%Y-%m-%dT%H:%M').replace(tzinfo=datetime.timezone.utc).astimezone(tz).date()
            per_day[d] = per_day.get(d, 0) + 1
        self.assertTrue(max(per_day.values()) <= 2)                              # daily_cap respected
        tt = store.rows('channel="tt"')
        self.assertEqual(len({r['scheduled_at'][:10] for r in tt}), 4)         # cap 1 -> one per day (different dates)

    def test_per_network_captions_titles_and_ai_line(self):
        c = cfg()
        c['ai_disclosure_line'] = 'Dini es un personaje animado con voz de IA.'
        m = manifest('p1')
        p = os.path.join(os.path.dirname(m), 'p1.json')
        d = json.load(open(p))
        d.update({'caption': 'Base.', 'hashtags': ['a', 'b', 'c', 'd', 'e', 'f'],
                  'captions': {'tiktok': 'Solo TikTok #x'}, 'titles': {'youtube': 'Titulo YT'}})
        json.dump(d, open(p, 'w'))
        plan.enqueue(p, c)
        rows = {r['channel']: r for r in store.rows('video_id=?', ('p1',))}
        keys = list(rows)
        ig = next(r for k, r in rows.items() if k.startswith('ig'))
        tt = next(r for k, r in rows.items() if k.startswith('tt'))
        yt = next(r for k, r in rows.items() if k.startswith('yt'))
        self.assertEqual(ig['caption'].count('#'), 4)                      # capped at 4 hashtags for Instagram
        self.assertIn('voz de IA', ig['caption'])                          # AI line in the text
        self.assertEqual(tt['caption'], 'Solo TikTok #x')                  # hand-written, no AI line (TikTok has a switch)
        self.assertEqual(yt['title'], 'Titulo YT')
        self.assertTrue(keys)

    def test_no_duplicates(self):
        c = cfg()
        p = manifest('dup')
        self.assertTrue(plan.enqueue(p, c)[0])
        self.assertFalse(plan.enqueue(p, c)[0])
        self.assertEqual(len(store.rows()), 3)

    def test_run_uploads_once_and_posts_per_time(self):
        c = cfg()
        plan.enqueue(manifest('r1'), c)
        publish.cmd_run(c, lookahead_h=24 * 90)
        uploads = [x for x in CALLS if x[0].endswith('/upload')]
        posts = [x for x in CALLS if x[0].endswith('/posts')]
        self.assertEqual(len(uploads), 1)                                         # one upload for the video
        self.assertEqual(len(posts), 3)                                           # 3 channels, 3 different slots
        for path, auth, ctype, body in posts:
            self.assertEqual(auth, 'test-key')
            j = json.loads(body)
            self.assertEqual(j['type'], 'schedule')
            self.assertTrue(j['date'].endswith(':00.000Z'))
            it = j['posts'][0]
            self.assertEqual(it['value'][0]['image'][0], {'id': 'vid-1', 'path': 'https://up.example/vid.mp4'})
            self.assertIn('#a #b', it['value'][0]['content'])
        self.assertTrue(uploads[0][2].startswith('multipart/form-data; boundary='))
        self.assertEqual({r['status'] for r in store.rows()}, {'sent'})

    def test_safe_network_defaults(self):
        s = postiz.settings_for({'network': 'tiktok'}, 'T' * 200)
        self.assertEqual(s['privacy_level'], 'SELF_ONLY')
        self.assertTrue(s['video_made_with_ai'])
        self.assertEqual(len(s['title']), 90)
        y = postiz.settings_for({'network': 'youtube'}, 'Y' * 200)
        self.assertEqual((y['type'], len(y['title'])), ('private', 100))
        self.assertEqual(postiz.settings_for({'network': 'instagram'}, 't')['post_type'], 'post')

    def test_failure_is_recorded(self):
        c = cfg()
        plan.enqueue(manifest('f1'), c)
        os.environ['POSTIZ_API_URL'] = 'http://127.0.0.1:9/api/public/v1'
        try:
            publish.cmd_run(c, lookahead_h=24 * 90)
        finally:
            os.environ['POSTIZ_API_URL'] = f'http://127.0.0.1:{self.srv.server_port}/api/public/v1'
        self.assertEqual({r['status'] for r in store.rows()}, {'failed'})
        self.assertIn('inalcanzable', store.rows()[0]['error'])


if __name__ == '__main__':
    unittest.main()
