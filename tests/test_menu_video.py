import os, sys, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from cf import menu_video as mv  # noqa: E402


def dish(i, name, price, **kw):
    d = {'id': f'd{i}', 'name': name, 'nameOther': '', 'description': '', 'descriptionOther': '', 'status': 'active',
         'category': 'x', 'priceType': 'base', 'priceMinor': price, 'availability': 'available', 'variants': []}
    d.update(kw)
    return d


PAYLOAD = {'business': {'slug': 'maya', 'name': 'Maya Café'},
           'menu': {'currency': 'USD', 'dishOfTheWeek': 'd2', 'dishes': [
               dish(1, 'Bandeja paisa', 1850), dish(2, 'Arepa con queso', 650, description='Maíz recién molido'),
               dish(3, 'Sancocho', 1500), dish(4, 'Agotado', 900, availability='sold_out'),
               dish(5, 'Oculto', 900, status='hidden'), dish(6, 'Sin precio', 0)]}}


class MenuVideo(unittest.TestCase):
    def test_money(self):
        self.assertEqual(mv.money(1850), '$18.50')
        self.assertEqual(mv.money(600), '$6')

    def test_sizes_show_from_price(self):
        d = dish(9, 'Jugo', 0, priceType='sizes', variants=[{'id': 'v1', 'title': 'S', 'priceMinor': 500},
                                                           {'id': 'v2', 'title': 'L', 'priceMinor': 800}])
        self.assertEqual(mv.dish_price(d), 'desde $5')

    def test_only_available_visible_priced_dishes(self):
        names = {d['name'] for d in mv.pick_dishes(PAYLOAD['menu'], 10, '2026-11-08')}
        self.assertEqual(names, {'Bandeja paisa', 'Arepa con queso', 'Sancocho'})

    def test_dish_of_the_week_goes_first_and_rotation_is_stable(self):
        a = mv.pick_dishes(PAYLOAD['menu'], 3, '2026-11-08')
        self.assertEqual(a[0]['id'], 'd2')
        self.assertEqual(a, mv.pick_dishes(PAYLOAD['menu'], 3, '2026-11-08'))

    def test_top3_job(self):
        job = mv.build_job(PAYLOAD, '2026-11-08', 'top3', client='maya')
        self.assertEqual(job['id'], 'menu-maya-top3-2026-11-08')
        self.assertRegex(job['id'], r'^[a-z0-9][a-z0-9_-]{1,80}$')
        self.assertEqual([s['type'] for s in job['scenes']], ['hook', 'step', 'outro'])
        self.assertEqual(len(job['scenes'][1]['points']), 3)
        self.assertEqual(job['client'], 'maya')

    def test_prices_are_shown_never_spoken(self):
        job = mv.build_job(PAYLOAD, '2026-11-08', 'top3')
        for s in job['scenes']:
            self.assertNotIn('$', s['speak'])

    def test_no_native_ordering_or_invented_claims(self):
        text = str(mv.build_job(PAYLOAD, '2026-11-08', 'top3')).lower()
        for bad in ('pide aquí', 'ordena', 'ventas', 'aumenta', '%'):
            self.assertNotIn(bad, text)

    def test_thin_menu_returns_none(self):
        thin = {'business': {'slug': 'x'}, 'menu': {'currency': 'USD', 'dishes': [dish(1, 'Solo uno', 500)]}}
        self.assertIsNone(mv.build_job(thin, '2026-11-08', 'top3'))
        self.assertIsNotNone(mv.build_job(thin, '2026-11-08', 'estrella'))

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            mv.build_job(PAYLOAD, '2026-11-08', 'nope')


if __name__ == '__main__':
    unittest.main()
