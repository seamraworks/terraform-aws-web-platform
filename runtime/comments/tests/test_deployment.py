import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deployment import load_deployment, validate_config
from moderator import Database, ModerationAdapter
from web_platform_moderation import ModerationResult, ProviderError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('renderer', ROOT / 'render-runtime.py')
renderer = importlib.util.module_from_spec(spec); spec.loader.exec_module(renderer)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.config = json.loads((ROOT / 'config.example.json').read_text())
        self.config.update(origin_secret='a' * 48, remark_secret='test-signing', admin_password='test-admin',
                           webhook_secret='test-webhook', backup_bucket='example-backups')
        self.descriptor = {'region': 'eu-central-1', 'site_id': 'example', 'public_url': 'https://comments.example.com',
                           'origin_hostname': 'comments-origin.example.com', 'config_parameter': '/example/comments/config',
                           'backup_bucket': 'example-backups', 'host_iam_user': 'example-comments'}

    def deployment(self, value):
        path = self.directory / 'descriptor.json'; path.write_text(json.dumps(value))
        return load_deployment(path)

    def test_anonymous_and_disabled_moderation_need_no_external_credentials(self):
        deployment = self.deployment(self.descriptor)
        validate_config(self.config, deployment)
        renderer.render_files(self.config, deployment, self.directory / 'rendered')
        result = ModerationAdapter(self.config, Database(self.directory / 'state.sqlite')).classify(
            {'orig': 'Question', 'locator': {'url': 'https://www.example.com/journal/example.html'}})
        self.assertEqual(result['provider'], 'none')
        self.assertEqual(result['decision'], 'keep')

    def test_two_deployments_render_independent_identity_and_branding(self):
        for site in ('one', 'two'):
            descriptor = {**self.descriptor, 'site_id': site, 'service_name': site + '-comments',
                          'public_url': 'https://comments.' + site + '.example.com',
                          'origin_hostname': 'origin.' + site + '.example.com', 'runtime_dir': '/opt/' + site + '-comments',
                          'config_dir': '/etc/' + site + '-comments'}
            deployment = self.deployment(descriptor)
            config = {**self.config, 'site': site, 'brand_name': site.capitalize(),
                      'public_url': descriptor['public_url'], 'article_hosts': ['www.' + site + '.example.com']}
            target = self.directory / site
            renderer.render_files(config, deployment, target)
            self.assertIn('name: ' + site + '-comments', (target / 'compose.yaml').read_text())
            self.assertIn(descriptor['origin_hostname'], (target / 'Caddyfile').read_text())
            self.assertIn(site.capitalize(), (target / 'templates/email_confirmation_login.html.tmpl').read_text())
            self.assertTrue((target / 'systemd' / (site + '-comments.service')).exists())

    def test_adoption_preserves_existing_paths_and_origin_header(self):
        deployment = self.deployment({**self.descriptor, 'runtime_dir': '/opt/legacy-comments', 'config_dir': '/etc/legacy-comments',
                                      'service_name': 'legacy-comments', 'origin_header': 'X-Legacy-Origin'})
        renderer.render_files(self.config, deployment, self.directory / 'legacy')
        self.assertIn('X-Legacy-Origin', (self.directory / 'legacy/Caddyfile').read_text())
        self.assertIn('/etc/legacy-comments/config.json', (self.directory / 'legacy/compose.yaml').read_text())

    def test_mismatched_identity_or_incomplete_enabled_provider_is_rejected(self):
        deployment = self.deployment(self.descriptor)
        for changes in ({'site': 'other'}, {'region': 'us-east-1'}, {'backup_bucket': 'other'},
                        {'moderation_provider': 'openai'}, {'google_client_id': 'enabled'},
                        {'mode': 'auto', 'admin_ids': []}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_config({**self.config, **changes}, deployment)

    def test_adapter_does_not_send_identity_email_or_ip(self):
        provider = patch('moderator.create_provider').start()
        self.addCleanup(patch.stopall)
        provider.return_value.classify.return_value = ModerationResult('review', 'Uncertain', 'custom')
        adapter = ModerationAdapter(self.config, Database(self.directory / 'state.sqlite'))
        adapter.classify({'orig': 'Question', 'title': 'Article', 'ip': '192.0.2.1',
                          'user': {'id': 'private-id', 'email': 'private@example.com'},
                          'locator': {'url': 'https://www.example.com/journal/example.html'}})
        request = provider.return_value.classify.call_args.args[0].to_dict()
        self.assertNotIn('private-id', json.dumps(request))
        self.assertNotIn('private@example.com', json.dumps(request))
        self.assertNotIn('192.0.2.1', json.dumps(request))


if __name__ == '__main__': unittest.main()
