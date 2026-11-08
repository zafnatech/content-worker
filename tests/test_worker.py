import os, sys, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import worker  # noqa: E402
from tests.test_menu_video import PAYLOAD  # noqa: E402


def fake(manifest=None, synced=1, menu=PAYLOAD):
    calls = {'render': 0, 'sync': 0}

    def render(job, out_dir):
        calls['render'] += 1
        return 'm.json', manifest or {'id': job['id'], 'voice': 'real', 'draft': False, 'voice_cost_usd_est': 0.2}

    def sync(cfg, ms, dry):
        calls['sync'] += 1
        return synced
    return calls, {'menu': lambda c: menu, 'render': render, 'sync': sync, 'channels': lambda: {'channels': []}}


class Worker(unittest.TestCase):
    def test_happy_path(self):
        calls, deps = fake()
        st, msg, cost = worker.make_one('maya', 'top3', '2026-11-08', deps=deps)
        self.assertEqual((st, calls['render'], calls['sync']), ('ok', 1, 1))
        self.assertEqual(cost, 0.2)

    def test_menu_error_is_reported_not_raised(self):
        calls, deps = fake()
        deps['menu'] = lambda c: (_ for _ in ()).throw(RuntimeError('401'))
        st, msg, _ = worker.make_one('maya', 'top3', '2026-11-08', deps=deps)
        self.assertEqual(st, 'error')
        self.assertEqual(calls['render'], 0)

    def test_thin_menu_skips_before_spending_voice(self):
        thin = {'business': {'slug': 'x'}, 'menu': {'currency': 'USD', 'dishes': []}}
        calls, deps = fake(menu=thin)
        st, _, _ = worker.make_one('x', 'top3', '2026-11-08', deps=deps)
        self.assertEqual((st, calls['render']), ('skip', 0))

    def test_no_consent_or_no_voice_never_registers(self):
        for m in ({'draft': True, 'voice': 'real', 'consent': 'sin permiso'}, {'draft': False, 'voice': 'PENDIENTE (x)'}):
            calls, deps = fake(manifest=m)
            st, _, _ = worker.make_one('maya', 'top3', '2026-11-08', deps=deps)
            self.assertEqual((st, calls['sync']), ('skip', 0))

    def test_sync_error_is_reported(self):
        calls, deps = fake()
        deps['sync'] = lambda *a: (_ for _ in ()).throw(RuntimeError('500'))
        self.assertEqual(worker.make_one('maya', 'top3', '2026-11-08', deps=deps)[0], 'error')

    def test_run_all_respects_voice_cap(self):
        os.environ['WORKER_CLIENTS'] = 'a,b,c'
        os.environ['WORKER_VOICE_USD_CAP'] = '0.30'
        calls, deps = fake()
        worker.run_all('2026-11-08', deps=deps)
        self.assertEqual(calls['render'], 2)   # 0.2 then 0.4 >= cap, third is not started

    def test_all_takes_every_published_restaurant_and_rotates(self):
        os.environ['WORKER_CLIENTS'] = 'ALL'
        os.environ['WORKER_MAX_PER_RUN'] = '2'
        os.environ['WORKER_VOICE_USD_CAP'] = '5'
        seen = []
        calls, deps = fake()
        deps['menu'] = lambda c: (seen.append(c), PAYLOAD)[1]
        deps['list'] = lambda: ['a', 'b', 'c']
        worker.run_all('2026-11-08', deps=deps)
        day1 = list(seen)
        self.assertEqual(len(day1), 2)
        seen.clear()
        worker.run_all('2026-11-09', deps=deps)
        self.assertNotEqual(day1, seen)   # the window moved
        self.assertEqual(len(set(day1 + seen)), 3)

    def test_all_with_listing_error_is_reported(self):
        os.environ['WORKER_CLIENTS'] = 'all'
        calls, deps = fake()
        deps['list'] = lambda: (_ for _ in ()).throw(RuntimeError('401'))
        self.assertEqual(worker.run_all('2026-11-08', deps=deps), 1)
        self.assertEqual(calls['render'], 0)

    def test_run_all_empty(self):
        os.environ['WORKER_CLIENTS'] = ''
        self.assertEqual(worker.run_all('2026-11-08'), 0)


if __name__ == '__main__':
    unittest.main()
