import unittest
from unittest.mock import patch

from qdp import utils


class ProxyRotationTests(unittest.TestCase):
    def setUp(self):
        utils.reset_proxy_cycle()
        utils.set_direct_mode(False)

    def tearDown(self):
        utils.reset_proxy_cycle()
        utils.set_direct_mode(False)

    def test_no_proxies_returns_none(self):
        with patch('qdp.utils.get_proxy_list', return_value=[]):
            self.assertIsNone(utils.get_active_proxy())
            self.assertIsNone(utils.get_active_proxy())

    def test_proxy_selection_is_deterministic_round_robin(self):
        with patch('qdp.utils.get_proxy_list', return_value=['https://p1', 'https://p2', 'https://p3']):
            picked = [utils.get_active_proxy() for _ in range(5)]

        self.assertEqual(picked, ['https://p1', 'https://p2', 'https://p3', 'https://p1', 'https://p2'])


if __name__ == '__main__':
    unittest.main()
