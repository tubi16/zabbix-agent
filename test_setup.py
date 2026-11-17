import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('wizard', Path(__file__).with_name('setup.py'))
wizard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wizard)


class WizardTests(unittest.TestCase):
    def test_invalid_ip_reprompts(self):
        with patch('builtins.input', side_effect=['invalid', '192.0.2.10']):
            self.assertEqual(wizard.prompt('IP', validator=wizard.ipaddress.ip_address), '192.0.2.10')

    def test_enroll_declined_runs_only_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            (target / 'install.py').touch()
            with patch('builtins.input', side_effect=['pc1', '192.0.2.10', '192.0.2.1', 'user@192.0.2.10', temp]), patch.object(wizard, 'ask', return_value=False), patch.object(wizard, 'run') as run:
                wizard.enroll(target)
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[-1], '--plan')

    def test_existing_directory_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / 'zabbix-server').mkdir()
            with patch.object(wizard.shutil, 'which', return_value='/usr/bin/git'), patch.object(wizard, 'run') as run:
                with self.assertRaises(SystemExit):
                    wizard.checkout('server', Path(temp), 'arch')
                run.assert_not_called()

    def test_wrong_origin_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / 'zabbix-agent' / '.git').mkdir(parents=True)
            with patch.object(wizard.shutil, 'which', return_value='/usr/bin/git'), patch.object(wizard.subprocess, 'check_output', return_value='https://example.org/other.git'), patch.object(wizard, 'run') as run:
                with self.assertRaises(SystemExit):
                    wizard.checkout('agent', Path(temp), 'arch')
                run.assert_not_called()

    def test_invalid_psk_cannot_apply_tls(self):
        with tempfile.TemporaryDirectory() as temp:
            key = Path(temp) / 'key'
            key.write_text('invalid')
            with patch.object(wizard, 'install_agent', return_value='agent2'), patch.object(wizard, 'ask', return_value=True), patch('builtins.input', side_effect=['host', '1', '1', '192.0.2.10', '10050', '192.0.2.1', str(key)]), patch.object(wizard, 'run') as run:
                with self.assertRaises(SystemExit):
                    wizard.agent(Path(temp), {'ID': 'arch'})
                run.assert_not_called()

    def test_plaintext_passive_has_ip_port_and_needs_no_key(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(wizard, 'install_agent', return_value='agent2'), patch.object(wizard, 'ask', return_value=True), patch('builtins.input', side_effect=['pc1', '1', '2', '192.0.2.10', '10060', '192.0.2.1']), patch.object(wizard, 'run') as run:
                wizard.agent(Path(temp), {'ID': 'arch'})
            args = list(map(str, run.call_args.args))
            self.assertIn('--unencrypted', args)
            self.assertNotIn('--key', args)
            self.assertEqual(args[args.index('--listen-ip') + 1], '192.0.2.10')
            self.assertEqual(args[args.index('--port') + 1], '10060')
            self.assertFalse((Path(temp) / 'private').exists())

    def test_active_ipv6_plaintext_can_be_declined(self):
        with patch.object(wizard, 'install_agent', return_value='classic'), patch.object(wizard, 'ask', return_value=False), patch('builtins.input', side_effect=['pc1', '2', '2', '2001:db8::1', '10051']), patch.object(wizard, 'run') as run:
            wizard.agent(Path('/tmp/not-created'), {'ID': 'arch'})
            run.assert_not_called()

    def test_active_psk_uses_selected_endpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            key = Path(temp) / 'key'; key.write_text('ab' * 32)
            with patch.object(wizard, 'install_agent', return_value='agent2'), patch.object(wizard, 'ask', return_value=True), patch('builtins.input', side_effect=['pc1', '2', '1', '2001:db8::1', '10061', str(key)]), patch.object(wizard, 'run') as run:
                wizard.agent(Path(temp), {'ID': 'arch'})
            args = list(map(str, run.call_args.args))
            self.assertEqual(args[args.index('--active') + 1], '[2001:db8::1]:10061')
            self.assertIn('--strict', args)
            self.assertIn('--key', args)

    def test_invalid_port_and_source_reprompt(self):
        with patch('builtins.input', side_effect=['0', '65536', '10050']):
            self.assertEqual(wizard.prompt('Port', validator=wizard.valid_port), '10050')
        with patch('builtins.input', side_effect=['192.0.2.1\nTLSAccept=unencrypted', '192.0.2.1']):
            self.assertEqual(wizard.prompt('Source', validator=wizard.valid_sources), '192.0.2.1')

    def test_compose_failure_prevents_start(self):
        def execute(*args, **kwargs):
            if args[:4] == ('docker', 'compose', 'config', '--quiet'):
                raise wizard.subprocess.CalledProcessError(1, args)
        with patch.object(wizard.shutil, 'which', return_value='/usr/bin/docker'), patch.object(wizard.subprocess, 'run') as process, patch.object(wizard, 'run', side_effect=execute) as run, patch.object(wizard, 'ask', return_value=True):
            process.return_value.returncode = 0
            with self.assertRaises(wizard.subprocess.CalledProcessError):
                wizard.server(Path('/tmp/example'), 'arch')
            self.assertFalse(any(call.args[:3] == ('docker', 'compose', 'up') for call in run.call_args_list))


if __name__ == '__main__':
    unittest.main()
