import os, sys, json, shutil, subprocess, tempfile, datetime, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import worker  # noqa: E402
from cf import autoq, clipvideo, music  # noqa: E402

UTC = datetime.timezone.utc


def job(**kw):
    j = {'id': 'plato-test-aaa', 'type': 'clip', 'run_after': '2026-11-10T06:30:00Z', 'brand': 'dinidine', 'business_name': 'Taco Riko',
         'clip_url': 'https://example.com/a.mp4', 'dish': 'Tacos', 'price_minor': 1850, 'hook': 'Mira este plato. Ahora dime que no.',
         'caption': 'Así se ve un plato en el menú digital. ¿Tu menú antoja así? Escríbenos.', 'post_date': '2026-11-11'}
    j.update(kw)
    return j


class Queue(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def put(self, name, obj):
        with open(os.path.join(self.d, name), 'w', encoding='utf-8') as f:
            f.write(obj if isinstance(obj, str) else json.dumps(obj))

    def at(self, h, m=0, day=10):
        return datetime.datetime(2026, 11, day, h, m, tzinfo=UTC)

    def test_window_is_open_only_for_an_hour(self):
        self.put('a.json', job())
        e = autoq.load(self.d)
        for now, want in ((self.at(6, 29), 'upcoming'), (self.at(6, 30), 'due'), (self.at(7, 0), 'due'), (self.at(7, 29), 'due'),
                          (self.at(7, 30), 'missed'), (self.at(23), 'missed')):
            due, up, miss, brk = autoq.split(e, now)
            got = 'due' if due else 'upcoming' if up else 'missed' if miss else 'broken'
            self.assertEqual(got, want, now)

    def test_hourly_ticks_hit_exactly_one_window_per_job(self):
        self.put('a.json', job())
        e = autoq.load(self.d)
        hits = [h for h in range(24) if autoq.split(e, self.at(h))[0]]
        self.assertEqual(hits, [7])

    def test_broken_file_does_not_stop_the_others(self):
        self.put('bad.json', '{nope')
        self.put('bad2.json', job(run_after='mañana'))
        self.put('bad3.json', job(type='carousel'))
        self.put('ok.json', job(id='plato-ok-bbb'))
        self.put('_ignored.json', job())
        due, up, miss, brk = autoq.split(autoq.load(self.d), self.at(7))
        self.assertEqual([j['id'] for _, j in due], ['plato-ok-bbb'])
        self.assertEqual(len(brk), 3)

    def test_empty_or_missing_queue(self):
        self.assertEqual(autoq.load(os.path.join(self.d, 'nope')), [])
        self.assertEqual(worker.run_auto(self.at(7), queue_dir=self.d), 0)


class Auto(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        with open(os.path.join(self.d, 'a.json'), 'w', encoding='utf-8') as f:
            json.dump(job(), f)
        self.calls = {'render': [], 'sync': []}

        def render(j, out_dir):
            self.calls['render'].append(j)
            return 'm.json', {'id': j['id'], 'voice': 'sin voz (texto + música)', 'draft': False, 'voice_cost_usd_est': 0.0}

        def sync(cfg, ms, dry):
            self.calls['sync'].append(ms)
            return 1
        self.deps = {'render_clip': render, 'sync': sync,
                     'channels': lambda: {'channels': [{'network': 'instagram', 'enabled': True}, {'network': 'tiktok', 'enabled': False}]}}

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_due_job_renders_and_registers_once(self):
        rc = worker.run_auto(datetime.datetime(2026, 11, 10, 7, 0, tzinfo=UTC), self.deps, queue_dir=self.d)
        self.assertEqual((rc, len(self.calls['render']), len(self.calls['sync'])), (0, 1, 1))
        sched = self.calls['render'][0]['schedule']
        self.assertEqual(list(sched), ['instagram'])           # only enabled networks
        self.assertEqual(sched['instagram'], '2026-11-11T17:00:00Z')   # Wed 12:00 America/New_York (EST)

    def test_not_due_does_nothing_and_needs_no_network(self):
        rc = worker.run_auto(datetime.datetime(2026, 11, 10, 9, 0, tzinfo=UTC), {}, queue_dir=self.d)
        self.assertEqual(rc, 0)

    def test_render_failure_is_reported_as_error(self):
        self.deps['render_clip'] = lambda j, o: (_ for _ in ()).throw(RuntimeError('no pude bajar el clip'))
        rc = worker.run_auto(datetime.datetime(2026, 11, 10, 7, 0, tzinfo=UTC), self.deps, queue_dir=self.d)
        self.assertEqual((rc, len(self.calls['sync'])), (1, 0))

    def test_old_weekly_flow_is_off_by_default(self):
        ran = []
        self.deps['channels'] = lambda: {'channels': []}
        orig = worker.run_week
        worker.run_week = lambda *a, **k: ran.append(1) or 0
        try:
            worker.run_auto(datetime.datetime(2026, 11, 14, 11, 0, tzinfo=UTC), self.deps, queue_dir=self.d)   # a Saturday 11:00Z
        finally:
            worker.run_week = orig
        self.assertEqual(ran, [])


class Clip(unittest.TestCase):
    def test_price_formats(self):
        self.assertEqual(clipvideo.fmt_price(1850), '$18.50')
        self.assertEqual(clipvideo.fmt_price(400), '$4')
        self.assertEqual(clipvideo.fmt_price(999, 'USD', 'sizes'), 'Desde $9.99')
        self.assertEqual(clipvideo.fmt_price(None), '')

    def test_hook_rules(self):
        self.assertEqual(clipvideo.pick_hook({'hook_id': 'h88', 'business_name': 'Taco Riko', 'dish': 'Esquites'}, 'dinidine'), 'Esquites de Taco Riko. Mira esto.')
        with self.assertRaises(clipvideo.ClipError):
            clipvideo.pick_hook({'hook': 'uno dos tres cuatro cinco seis siete ocho nueve'}, 'dinidine')
        with self.assertRaises(clipvideo.ClipError):
            clipvideo.pick_hook({'hook_id': 'h88'}, 'dinidine')   # template without data
        with self.assertRaises(clipvideo.ClipError):
            clipvideo.pick_hook({}, 'dinidine')

    def test_every_bank_hook_is_short(self):
        with open(os.path.join(HERE, 'brands', 'dinidine', 'hooks.json'), encoding='utf-8') as f:
            for h in json.load(f)['hooks']:
                self.assertLessEqual(clipvideo.words(h['text'].replace('{restaurante}', 'Taco Riko').replace('{plato}', 'Quesadilla')), 8, h)

    def test_validation(self):
        clipvideo.validate(job())
        for bad in ({'clip_url': 'http://x/a.mp4'}, {'id': 'Mal Id'}, {'music': 'rock'}, {'caption': ' '.join(['x'] * 60)}):
            with self.assertRaises(clipvideo.ClipError):
                clipvideo.validate(job(**bad))

    def test_cloudinary_tries_sharper_rendition_first(self):
        u = 'https://res.cloudinary.com/x/video/upload/q_auto,w_720,ac_none/a.mp4'
        self.assertEqual(clipvideo.candidate_urls(u), [u.replace('w_720', 'w_1080'), u])
        self.assertEqual(clipvideo.candidate_urls('https://backend.digidine.us/uploads/a.mp4'), ['https://backend.digidine.us/uploads/a.mp4'])

    def test_banned_phrase_blocks_render(self):
        from cf import guardrails
        banned = guardrails.banned_for('dinidine')
        if not banned:
            self.skipTest('no banned phrases configured')
        with self.assertRaises(clipvideo.ClipError):
            clipvideo.render(job(caption=f'Prueba {banned[0]} ahora'), tempfile.mkdtemp(), fetch=lambda u, d: u)

    def test_music_styles_differ_and_rotate(self):
        d = tempfile.mkdtemp()
        sizes = set()
        for s in music.STYLES:
            p = os.path.join(d, s + '.wav')
            music.make_preset(p, 3, s, 1)
            with open(p, 'rb') as f:
                sizes.add(hash(f.read()))
        self.assertEqual(len(sizes), len(music.STYLES))
        self.assertNotEqual(music.style_for(10), music.style_for(11))
        self.assertNotEqual(music.style_for(10, avoid=music.style_for(10)), music.style_for(10))
        shutil.rmtree(d)


@unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg not installed')
class PageJob(unittest.TestCase):
    def test_page_url_is_limited_to_our_public_https_pages(self):
        base = job(page_url='https://tacoriko.zafnatech.com/')
        base.pop('clip_url')
        clipvideo.validate(base)
        for bad in ('http://tacoriko.zafnatech.com/', 'https://evil.com/', 'https://a.zafnatech.com.evil.com/', 'https://u:p@a.zafnatech.com/'):
            with self.assertRaises(clipvideo.ClipError):
                clipvideo.validate(dict(base, page_url=bad))

    def test_page_job_records_instead_of_downloading(self):
        d = tempfile.mkdtemp()
        seen = {}
        real = clipvideo.capture_page
        clipvideo.capture_page = lambda url, dest, seconds=8: (seen.update(url=url), shutil.copy(os.path.join(d, 'src.mp4'), dest))
        try:
            import subprocess
            subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=540x960:rate=30:duration=8',
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', os.path.join(d, 'src.mp4')], check=True)
            j = job(page_url='https://tacoriko.zafnatech.com/', hook='Tu cliente ve esto al escanear.')
            j.pop('clip_url')
            _, m = clipvideo.render(j, os.path.join(d, 'out'), date_ordinal=1)
            self.assertEqual(seen['url'], 'https://tacoriko.zafnatech.com/')
            self.assertEqual(m['source_clip'], 'https://tacoriko.zafnatech.com/')
        finally:
            clipvideo.capture_page = real
            shutil.rmtree(d, ignore_errors=True)


class Memory(unittest.TestCase):
    def test_ffmpeg_threads_are_capped_so_a_big_host_cannot_exhaust_memory(self):
        """10 Nov 2026: Render killed the cron ("Out of memory, used over 2Gi") because ffmpeg sized its threads by the host."""
        seen = {}

        class Done:
            returncode = 0
            stderr = ''

        def fake_run(cmd, **kw):
            seen['cmd'] = cmd
            open(cmd[-1], 'wb').close()
            return Done()

        d = tempfile.mkdtemp()
        real = clipvideo.subprocess.run
        clipvideo.subprocess.run = fake_run
        try:
            clipvideo.compose('clip.mp4', ['a.png', 'b.png', 'c.png', 'd.png'], 'm.wav', os.path.join(d, 'o.mp4'), 1280, 720, 8.0)
        finally:
            clipvideo.subprocess.run = real
            shutil.rmtree(d, ignore_errors=True)
        cmd = seen['cmd']
        self.assertEqual(cmd.count('-threads'), 7)   # clip + 4 overlays + music + encoder
        self.assertIn('-filter_complex_threads', cmd)
        self.assertEqual(cmd[cmd.index('-filter_complex_threads') + 1], '1')
        self.assertEqual(cmd[cmd.index('libx264') + 1:cmd.index('libx264') + 3], ['-threads', '2'])


class Render(unittest.TestCase):
    def test_end_to_end_with_a_synthetic_clip(self):
        import subprocess
        d = tempfile.mkdtemp()
        src = os.path.join(d, 'src.mp4')
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=720x1280:rate=24:duration=4', '-pix_fmt', 'yuv420p', src], check=True)
        mp, m = clipvideo.render(job(), os.path.join(d, 'out'), date_ordinal=5, fetch=lambda u, dest: (shutil.copy(src, dest), u)[1])
        w, h, dur = clipvideo.probe(m['file'])
        self.assertEqual((w, h), (1080, 1920))
        self.assertGreaterEqual(dur, 6.9)   # a short clip is looped up to the 7 s minimum
        self.assertEqual((m['voice_chars'], m['draft'], m['ai_disclosure']), (0, False, True))
        self.assertTrue(any('IA' in v for v in m['verify_before_publish']))
        shutil.rmtree(d)


if __name__ == '__main__':
    unittest.main()


class CaptureGate(unittest.TestCase):
    def _mk(self, d, vf):
        out = os.path.join(d, 'c.mp4')
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', vf, '-t', '3', '-pix_fmt', 'yuv420p', out], check=True)
        return out

    def test_blank_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(clipvideo.ClipError):
                clipvideo.check_capture(self._mk(d, 'color=c=white:s=270x480:r=30'), 'x')

    def test_moving_page_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            clipvideo.check_capture(self._mk(d, 'testsrc2=s=270x480:r=30'), 'x')
