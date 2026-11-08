import os, sys, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from cf import guardrails, menu_video  # noqa: E402
from tests.test_menu_video import PAYLOAD  # noqa: E402


class Guardrails(unittest.TestCase):
    def test_generated_menu_job_is_clean_for_dinidine(self):
        self.assertEqual(guardrails.check(menu_video.build_job(PAYLOAD, '2026-11-08', 'top3')), [])

    def test_native_ordering_claim_is_blocked(self):
        job = {'brand': 'dinidine', 'scenes': [{'speak': 'Recibe PEDIDOS nativos hoy'}]}
        self.assertEqual(guardrails.check(job), ['pedidos nativos'])

    def test_accents_and_case_are_ignored(self):
        job = {'brand': 'lanidental', 'caption': 'Nuestro DIAGNÓSTICO en minutos'}
        self.assertIn('diagnóstico', guardrails.check(job))

    def test_verify_notes_are_not_public_text(self):
        job = {'brand': 'dinidine', 'verify': ['no prometer pedidos nativos'], 'scenes': [{'speak': 'Hola'}]}
        self.assertEqual(guardrails.check(job), [])

    def test_every_brand_declares_phrases(self):
        for slug in os.listdir(os.path.join(HERE, 'brands')):
            if os.path.exists(os.path.join(HERE, 'brands', slug, 'brand.json')):
                self.assertTrue(guardrails.banned_for(slug), slug)


if __name__ == '__main__':
    unittest.main()
