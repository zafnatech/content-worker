import os, sys, json, tempfile, threading, unittest, datetime, hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

TMP = tempfile.mkdtemp()
os.environ['PLATFORM_SYNC_STATE'] = os.path.join(TMP, 'state.json')
from publisher import platform_sync as ps  # noqa: E402

SEEN = {'cloud': [], 'ingest': []}
FAIL_INGEST = {'on': False}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if '/video/upload' in self.path:
            SEEN['cloud'].append((self.path, body))
            pid = body.split(b'name="public_id"\r\n\r\n')[1].split(b'\r\n')[0].decode()
            self._send(200, {'public_id': pid})
        else:
            SEEN['ingest'].append((self.headers.get('Authorization'), json.loads(body)))
            if FAIL_INGEST['on']:
                self._send(422, {'error': 'invalid lineage'})
            else:
                self._send(200, {'video_id': '3f2c1a40-6b0e-4a39-9d2b-1b7d9f6f1e%02d' % len(SEEN['ingest'])})

    def _send(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(raw)))
        self.end_headers(); self.wfile.write(raw)


SRV = HTTPServer(('127.0.0.1', 0), H)
threading.Thread(target=SRV.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{SRV.server_port}'
os.environ.update(CLOUDINARY_CLOUD_NAME='zafna', CLOUDINARY_UPLOAD_PRESET='preset1', CLOUDINARY_API_BASE=BASE,
                  CONTENT_INGEST_URL=BASE + '/api/content/ingest', CONTENT_INGEST_TOKEN='TOKEN-1')

CFG = {'timezone': 'America/New_York', 'ai_disclosure_line': 'Dini es un personaje animado con voz generada por IA.',
       'channels': [
           {'key': 'dinidine-instagram', 'brand': 'dinidine', 'network': 'instagram', 'integration_id': 'int-ig-000001', 'enabled': True, 'daily_cap': 1, 'slots': ['12:00']},
           {'key': 'dinidine-youtube', 'brand': 'dinidine', 'network': 'youtube', 'integration_id': 'int-yt-000001', 'enabled': True, 'daily_cap': 1, 'slots': ['17:00'], 'settings': {'type': 'private'}},
           {'key': 'dinidine-off', 'brand': 'dinidine', 'network': 'tiktok', 'integration_id': 'int-tt-000001', 'enabled': False, 'daily_cap': 1, 'slots': ['18:00']},
       ]}
NOW = datetime.datetime(2026, 11, 6, 20, 0, tzinfo=datetime.timezone.utc)


def manifest(vid, **kw):
    f = os.path.join(TMP, vid + '.mp4')
    open(f, 'wb').write(b'fake-mp4-' + vid.encode())
    m = {'id': vid, 'title': 'T ' + vid, 'brand': 'dinidine', 'draft': False, 'voice': 'real', 'caption': 'Hola.', 'hashtags': ['DiniDine', '#restaurantes'],
         'file': f, 'duration_s': 9.3, 'voice_chars': 146, 'voice_cost_usd_est': 0.0058, 'verify_before_publish': ['revisa']}
    m.update(kw)
    return (os.path.join(TMP, vid + '.json'), m)


class T(unittest.TestCase):
    def setUp(self):
        SEEN['cloud'].clear(); SEEN['ingest'].clear(); FAIL_INGEST['on'] = False
        if os.path.exists(ps.STATE):
            os.remove(ps.STATE)
        self.logs = []

    def run_sync(self, ms, dry=False):
        return ps.sync_new(CFG, ms, dry=dry, now=NOW, log=self.logs.append)

    def test_registers_video_with_hash_slots_and_token(self):
        m = manifest('uno')
        self.assertEqual(self.run_sync([m]), 1)
        tok, p = SEEN['ingest'][0]
        self.assertEqual(tok, 'Bearer TOKEN-1')
        self.assertEqual(p['brand'], 'dinidine'); self.assertEqual(p['job_key'], 'uno')
        self.assertEqual(p['media_key'], 'zafnatech/dinidine/contenido/2026-11/uno')
        self.assertEqual(p['hashtags'], ['DiniDine', 'restaurantes'])
        self.assertEqual(p['lineage']['asset_hash'], hashlib.sha256(b'fake-mp4-uno').hexdigest())
        chans = {x['channel_key']: x['scheduled_at'] for x in p['publications']}
        self.assertEqual(set(chans), {'dinidine-instagram', 'dinidine-youtube'})   # the disabled channel is left out
        self.assertEqual(chans['dinidine-instagram'], '2026-11-07T17:00:00Z')      # 12:00 New York next day (today's slot passed)
        self.assertEqual(p['verify_notes'], ['revisa'])
        self.assertNotIn('caption', p['publications'][0])                           # no per-network text unless hand-written
        self.assertIn('uno', ps.synced_ids())

    def test_second_run_does_nothing_and_next_video_takes_the_next_day(self):
        self.run_sync([manifest('uno')])
        self.assertEqual(self.run_sync([manifest('uno'), manifest('dos')]), 1)
        self.assertEqual(len(SEEN['ingest']), 2)
        days = {x['channel_key']: x['scheduled_at'] for x in SEEN['ingest'][1][1]['publications']}
        self.assertEqual(days['dinidine-instagram'], '2026-11-08T17:00:00Z')       # daily_cap 1: the first video already took Nov 7

    def test_per_network_text_and_lineage(self):
        self.run_sync([manifest('padre')])
        hijo = manifest('hijo', captions={'youtube': 'Texto para YouTube'}, titles={'youtube': 'Titulo YT'},
                        lineage={'parent_job': 'padre', 'change_kind': 'new_piece', 'substantive_change': 'Responde otra pregunta'})
        self.run_sync([hijo])
        p = SEEN['ingest'][1][1]
        yt = [x for x in p['publications'] if x['channel_key'] == 'dinidine-youtube'][0]
        self.assertEqual((yt['caption'], yt['title']), ('Texto para YouTube', 'Titulo YT'))
        self.assertEqual(p['lineage']['parent_video_id'], '3f2c1a40-6b0e-4a39-9d2b-1b7d9f6f1e01')
        self.assertEqual(p['lineage']['change_kind'], 'new_piece')

    def test_unknown_parent_is_refused_without_uploading_a_publication(self):
        self.run_sync([manifest('huerfano', lineage={'parent_job': 'nadie', 'substantive_change': 'x'})])
        self.assertEqual(SEEN['ingest'], [])
        self.assertNotIn('huerfano', ps.synced_ids())

    def test_drafts_silent_videos_and_missing_files_are_skipped(self):
        silent = manifest('mudo', voice='PENDIENTE 2/7')
        draft = manifest('borrador', draft=True)
        missing = manifest('nofile'); missing[1]['file'] = os.path.join(TMP, 'no-existe.mp4')
        self.assertEqual(self.run_sync([silent, draft, missing]), 0)
        self.assertEqual((SEEN['cloud'], SEEN['ingest']), ([], []))

    def test_server_rejection_is_not_marked_synced_and_does_not_burn_a_slot(self):
        FAIL_INGEST['on'] = True
        self.assertEqual(self.run_sync([manifest('tres')]), 0)
        self.assertNotIn('tres', ps.synced_ids())
        self.assertTrue(any('invalid lineage' in l for l in self.logs))
        FAIL_INGEST['on'] = False
        self.assertEqual(self.run_sync([manifest('tres')]), 1)
        first = {x['channel_key']: x['scheduled_at'] for x in SEEN['ingest'][-1][1]['publications']}
        self.assertEqual(first['dinidine-instagram'], '2026-11-07T17:00:00Z')

    def test_dry_run_touches_nothing(self):
        self.assertEqual(self.run_sync([manifest('seco')], dry=True), 0)
        self.assertEqual((SEEN['cloud'], SEEN['ingest']), ([], []))
        self.assertFalse(os.path.exists(ps.STATE))

    def test_seed_sql_matches_the_platform_table(self):
        sql = ps.channels_sql(CFG, 'dinidine')
        self.assertIn('insert into public.content_channels (brand_id, key, network, display_name, integration_id, enabled, daily_cap, slots, settings)', sql)
        self.assertIn("array['12:00']::text[]", sql)
        self.assertIn("ai_disclosure_line", sql)
        self.assertIn('on conflict (brand_id, key) do update', sql)


if __name__ == '__main__':
    unittest.main()
