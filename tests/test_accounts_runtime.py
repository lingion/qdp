import os
import tempfile
import unittest

from qdp.accounts import AccountConfigError, load_account_config, load_account_config_or_raise


class AccountRuntimeConfigTests(unittest.TestCase):
    def test_load_account_config_prefers_environment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = os.path.join(tmpdir, 'config.ini')
            with open(cfg, 'w', encoding='utf-8') as fp:
                fp.write('[DEFAULT]\napp_id = cfg-app\nuser_auth_token = cfg-token\nuse_token = true\n')

            loaded = load_account_config(
                cfg,
                env={
                    'QOBUZ_APP_ID': 'env-app',
                    'QOBUZ_USER_AUTH_TOKEN': 'env-token',
                    'QDP_USE_TOKEN': 'true',
                },
            )

        self.assertEqual(loaded.app_id, 'env-app')
        self.assertEqual(loaded.user_auth_token, 'env-token')
        self.assertTrue(loaded.use_token)
        self.assertEqual(loaded.source, 'environment')

    def test_load_account_config_or_raise_surfaces_validation_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = os.path.join(tmpdir, 'config.ini')
            with open(cfg, 'w', encoding='utf-8') as fp:
                fp.write('[DEFAULT]\nuse_token = true\n')

            with self.assertRaises(AccountConfigError) as ctx:
                load_account_config_or_raise(cfg, env={})

        self.assertTrue(any('Missing app_id' in err for err in ctx.exception.errors))
        self.assertTrue(any('Missing user_auth_token' in err for err in ctx.exception.errors))


if __name__ == '__main__':
    unittest.main()
