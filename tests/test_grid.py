import os, sys, datetime, json, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault('PLATFORM_SYNC_STATE', os.path.join(HERE, 'out', '.test-state.json'))
import worker  # noqa: E402
from cf import grid, scripts, guardrails  # noqa: E402
from publisher import platform_sync as ps  # noqa: E402
from tests.test_menu_video import PAYLOAD  # noqa: E402

D = datetime.date
NOW = datetime.datetime(2026, 11, 8, 12, 0, tzinfo=datetime.timezone.utc)
ALL = {'facebook', 'instagram', 'tiktok', 'youtube', 'linkedin'}


class GridMath(unittest.TestCase):
    def test_cycle_is_eleven_weeks_for_75_days(self):
        self.assertEqual(grid.cycle_weeks(75), 11)

    def test_same_piece_never_twice_inside_75_days(self):
        for pool in (6, 11, 14):
            seen = {}
            for w in range(0, 80):
                d = D(2026, 11, 9) + datetime.timedelta(days=7 * w)
                i = grid.pick_index(d, pool, 75)
                if i is None:
                    continue
                if i in seen:
                    self.assertGreaterEqual((d - seen[i]).days, 75, (pool, i))
                seen[i] = d

    def test_small_pool_leaves_weeks_empty(self):
        got = [grid.pick_index(D(2026, 11, 9) + datetime.timedelta(days=7 * w), 3) for w in range(11)]
        self.assertEqual(sum(x is None for x in got), 8)

    def test_utc_conversion_follows_daylight_saving(self):
        self.assertEqual(grid.to_utc_iso(D(2026, 11, 9), '12:00', 'America/New_York'), '2026-11-09T17:00:00Z')   # EST
        self.assertEqual(grid.to_utc_iso(D(2026, 7, 6), '12:00', 'America/New_York'), '2026-07-06T16:00:00Z')    # EDT

    def test_plan_skips_thanksgiving_and_weekends(self):
        g = grid.load_grid('dinidine')
        days = [p['date'].isoformat() for p in grid.plan(g, D(2026, 11, 23), 7)]
        self.assertNotIn('2026-11-26', days)
        self.assertIn('2026-11-25', days)
        self.assertIn('2026-11-28', days)       # Small Business Saturday (special)
        self.assertNotIn('2026-11-29', days)    # Sunday: nothing

    def test_plan_limits_to_enabled_networks(self):
        g = grid.load_grid('dinidine')
        p = grid.plan(g, D(2026, 11, 9), 1, {'facebook'})
        self.assertEqual(list(p[0]['schedule']), ['facebook'])


class Bank(unittest.TestCase):
    def setUp(self):
        self.old = {k: os.environ.pop(k, None) for k in ('WORKER_BANK_APPROVED', 'WORKER_UNLOCK')}

    def tearDown(self):
        for k, v in self.old.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def test_nothing_renders_until_bank_is_approved(self):
        bank = scripts.load_bank('dinidine')
        self.assertTrue(bank)
        self.assertEqual(scripts.pool(bank, 'consejo'), [])
        os.environ['WORKER_BANK_APPROVED'] = '1'
        self.assertEqual(len(scripts.pool(bank, 'consejo')), 11)

    def test_locked_pieces_need_their_gate(self):
        os.environ['WORKER_BANK_APPROVED'] = '1'
        bank = scripts.load_bank('dinidine')
        self.assertEqual(scripts.pool(bank, 'agentes'), [])
        self.assertTrue(all(not s['needs'] for s in scripts.pool(bank, 'producto')))
        os.environ['WORKER_UNLOCK'] = 'tv,agents'
        self.assertEqual(len(scripts.pool(bank, 'agentes')), 1)

    def test_every_script_passes_the_brand_rules_and_has_unique_ascii_id(self):
        bank = scripts.load_bank('dinidine')
        ids = [s['id'] for s in bank]
        self.assertEqual(len(ids), len(set(ids)))
        for s in bank:
            self.assertTrue(s['id'].isascii(), s['id'])
            job = scripts.build_job(s, D(2026, 11, 9))
            self.assertEqual(guardrails.check(job), [], s['id'])
            blob = ' ' + ' '.join(guardrails._texts(job)).lower() + ' '
            for bad in ('sin contrato', 'garantiz', '$', ' por mes ', '/mes', 'mensual', 'dólares', 'gratis por'):
                self.assertNotIn(bad, blob, (s['id'], bad))

    def test_job_shape(self):
        s = scripts.load_bank('dinidine')[0]
        job = scripts.build_job(s, D(2026, 11, 9), schedule={'facebook': '2026-11-09T15:00:00Z'})
        self.assertEqual([c['type'] for c in job['scenes']], ['hook', 'step', 'outro'])
        self.assertTrue(job['id'].endswith('2026-11-09'))
        self.assertEqual(job['schedule'], {'facebook': '2026-11-09T15:00:00Z'})
        self.assertNotIn('**', job['title'])


class Week(unittest.TestCase):
    def setUp(self):
        self.old = {k: os.environ.get(k) for k in ('WORKER_BANK_APPROVED', 'WORKER_UNLOCK')}
        os.environ['WORKER_BANK_APPROVED'] = '1'
        os.environ.pop('WORKER_UNLOCK', None)

    def tearDown(self):
        for k, v in self.old.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def test_resolution_is_deterministic(self):
        cl = ['a', 'b', 'c']
        a = worker.resolve_week('dinidine', D(2026, 11, 9), 7, ALL, cl, now=NOW)
        b = worker.resolve_week('dinidine', D(2026, 11, 9), 7, ALL, cl, now=NOW)
        self.assertEqual([(x['id'], x['schedule']) for x in a], [(x['id'], x['schedule']) for x in b])
        self.assertEqual([x['kind'] for x in a][:2], ['script', 'menu'])

    def test_tuesday_is_the_menu_and_restaurants_rotate_weekly(self):
        cl = [f'r{i}' for i in range(19)]
        seen = []
        for w in range(19):
            start = D(2026, 11, 10) + datetime.timedelta(days=7 * w)
            it = [x for x in worker.resolve_week('dinidine', start, 1, ALL, cl, now=NOW - datetime.timedelta(days=400))][0]
            self.assertEqual(it['kind'], 'menu')
            seen.append(it['client'])
        self.assertEqual(len(set(seen)), 19)

    def test_special_date_wins_over_the_weekly_pillar(self):
        it = worker.resolve_week('dinidine', D(2026, 11, 25), 1, ALL, ['a'], now=NOW)[0]
        self.assertEqual(it['script']['id'], 'fecha-gracias-2026')

    def test_special_without_approval_is_empty_not_invented(self):
        os.environ['WORKER_BANK_APPROVED'] = '0'
        it = worker.resolve_week('dinidine', D(2026, 11, 25), 1, ALL, ['a'], now=NOW)[0]
        self.assertEqual(it['kind'], 'empty')

    def test_thursday_falls_back_to_objection_while_agents_are_locked(self):
        it = worker.resolve_week('dinidine', D(2026, 11, 12), 1, ALL, ['a'], now=NOW)[0]
        self.assertEqual(it['script']['pillar'], 'objecion')

    def test_times_too_close_are_dropped(self):
        late = datetime.datetime(2026, 11, 9, 14, 0, tzinfo=datetime.timezone.utc)   # Monday 9:00 ET
        it = worker.resolve_week('dinidine', D(2026, 11, 9), 1, ALL, ['a'], now=late)
        self.assertTrue(all(t >= '2026-11-09T20:00:00Z' for t in it[0]['schedule'].values()))

    def test_run_week_registers_with_fixed_times_and_is_idempotent(self):
        synced, rendered = [], []

        def render(job, out_dir):
            rendered.append(job)
            return 'm.json', {'id': job['id'], 'voice': 'real', 'draft': False, 'voice_cost_usd_est': 0.01}

        def sync(cfg, ms, dry):
            synced.append(ms[0][1]['id'])
            return 1
        deps = {'menu': lambda c: PAYLOAD, 'render': render, 'sync': sync, 'now': NOW, 'list': lambda: ['maya'],
                'channels': lambda: {'channels': [{'network': 'facebook', 'enabled': True}, {'network': 'instagram', 'enabled': True}]}}
        os.environ['WORKER_CLIENTS'] = 'all'
        try:
            rc = worker.run_week(D(2026, 11, 9), 3, deps)
        finally:
            os.environ.pop('WORKER_CLIENTS', None)
        self.assertEqual(rc, 0)
        self.assertEqual(len(synced), 3)
        self.assertTrue(all(set(j['schedule']) <= {'facebook', 'instagram'} for j in rendered))
        self.assertEqual(rendered[0]['schedule']['facebook'], '2026-11-09T15:00:00Z')


class FixedSchedule(unittest.TestCase):
    def test_manifest_schedule_overrides_slot_state(self):
        cfg = {'timezone': 'America/New_York', 'channels': [
            {'key': 'd-fb', 'brand': 'dinidine', 'network': 'facebook', 'enabled': True, 'integration_id': 'x', 'slots': ['12:00'], 'daily_cap': 1},
            {'key': 'd-tt', 'brand': 'dinidine', 'network': 'tiktok', 'enabled': True, 'integration_id': 'y', 'slots': ['12:00'], 'daily_cap': 1}]}
        state = {'slots': {}, 'videos': {}}
        m = {'id': 'j', 'brand': 'dinidine', 'title': 't', 'caption': 'c', 'schedule': {'facebook': '2026-11-10T15:00:00Z'}}
        p = ps.build_payload(m, 'k', 'h', cfg, state, NOW)
        self.assertEqual([(x['channel_key'], x['scheduled_at']) for x in p['publications']], [('d-fb', '2026-11-10T15:00:00Z')])
        self.assertEqual(state['slots'], {})   # fixed times leave no state behind

    def test_schedule_with_no_matching_network_is_an_error(self):
        cfg = {'channels': [{'key': 'd-fb', 'brand': 'dinidine', 'network': 'facebook', 'enabled': True, 'integration_id': 'x'}]}
        with self.assertRaises(ps.SyncError):
            ps.build_payload({'id': 'j', 'brand': 'dinidine', 'schedule': {'tiktok': '2026-11-10T15:00:00Z'}}, 'k', 'h', cfg, {'slots': {}, 'videos': {}}, NOW)


if __name__ == '__main__':
    unittest.main()
