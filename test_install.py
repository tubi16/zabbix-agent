import argparse
import contextlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import install as installer


class AgentTests(unittest.TestCase):
    def test_plaintext_modes_remove_old_tls_without_creating_or_deleting_keys(self):
        for binary in ('zabbix_agentd', 'zabbix_agent2'):
            for active in (False, True):
                with self.subTest(binary=binary, active=active), tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
                    root = Path(tmp)
                    config = root / 'agent.conf'
                    key = root / 'old.psk'; key.write_text('ab' * 32)
                    config.write_text(f'Server=127.0.0.1\nServerActive=old:10051\nStartAgents=0\nHostname=old\nTLSConnect=psk\nTLSAccept=psk\nTLSPSKIdentity=old\nTLSPSKFile={key}\n')
                    stack.enter_context(patch.object(installer, 'TLS_DIRECTORY', root / 'tls'))
                    stack.enter_context(patch.object(installer, 'select_agent', return_value=('agent.service', binary, str(config))))
                    stack.enter_context(patch.object(installer.os, 'geteuid', return_value=0))
                    stack.enter_context(patch.object(installer.shutil, 'which', return_value='/usr/bin/' + binary))
                    ownership = stack.enter_context(patch.object(installer.os, 'chown'))
                    run = stack.enter_context(patch.object(installer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)))
                    args = ['installer', '--host', 'pc1', '--unencrypted']
                    args += ['--active', '[2001:db8::1]:10051'] if active else ['--server', '192.0.2.1', '--listen-ip', '192.0.2.10', '--port', '10060']
                    stack.enter_context(patch.object(sys, 'argv', args))
                    installer.main()
                    text = config.read_text()
                    self.assertIn('TLSConnect=unencrypted', text)
                    self.assertIn('TLSAccept=unencrypted', text)
                    self.assertNotIn('TLSPSK', text)
                    self.assertEqual(key.read_text(), 'ab' * 32)
                    self.assertFalse((root / 'tls').exists())
                    ownership.assert_not_called()
                    if active:
                        self.assertNotRegex(text, r'(?m)^Server=')
                        self.assertIn('ServerActive=[2001:db8::1]:10051', text)
                    else:
                        self.assertNotRegex(text, r'(?m)^ServerActive=')
                        self.assertIn('ListenIP=192.0.2.10', text)
                        self.assertIn('ListenPort=10060', text)
                        self.assertIn('192.0.2.1', text)
                        if binary == 'zabbix_agentd': self.assertIn('StartAgents=3', text)
                    self.assertEqual(run.call_args_list[0].args[0][1], '-T')
                    self.assertEqual(run.call_args_list[1].args[0][:2], ['systemctl', 'restart'])

    def test_plaintext_validation_failure_restores_encrypted_config(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            config = Path(tmp) / 'agent.conf'
            original = 'Server=127.0.0.1\nTLSAccept=psk\nTLSConnect=psk\n'
            config.write_text(original)
            stack.enter_context(patch.object(installer, 'select_agent', return_value=('agent.service', 'zabbix_agent2', str(config))))
            stack.enter_context(patch.object(installer.os, 'geteuid', return_value=0))
            stack.enter_context(patch.object(installer.shutil, 'which', return_value='/usr/bin/zabbix_agent2'))
            run = stack.enter_context(patch.object(installer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)))
            stack.enter_context(patch.object(sys, 'argv', ['installer', '--host', 'pc1', '--unencrypted', '--server', '192.0.2.1']))
            with self.assertRaisesRegex(SystemExit, 'validation failed'): installer.main()
            self.assertEqual(config.read_text(), original)
            self.assertEqual(run.call_count, 1)

    def test_plaintext_rejects_conflicting_psk_options_before_mutation(self):
        for option in (['--key', '/not/read'], ['--strict']):
            with self.subTest(option=option), patch.object(sys, 'argv', ['installer', '--host', 'pc1', '--server', '192.0.2.1', '--unencrypted'] + option), patch.object(installer, 'select_agent') as select:
                with self.assertRaises(SystemExit): installer.main()
                select.assert_not_called()

    def test_active_endpoint_rejects_config_injection(self):
        self.assertEqual(installer.active_endpoint('proxy.example.com:10051'), 'proxy.example.com:10051')
        self.assertEqual(installer.active_endpoint('[2001:db8::1]:10051'), '[2001:db8::1]:10051')
        for value in ('host:0', 'host:65536', 'host:10051\nTLSConnect=unencrypted', 'host1,host2:10051'):
            with self.assertRaises(argparse.ArgumentTypeError):
                installer.active_endpoint(value)

    def test_active_only_removes_passive_listener_and_validates_before_restart(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            root = Path(tmp)
            config = root / 'agent.conf'
            config.write_text('Server=127.0.0.1\nServerActive=old:10051\nHostname=old\n')
            key = root / 'key.psk'
            key.write_text('ab' * 32)
            stack.enter_context(patch.object(installer, 'TLS_DIRECTORY', root / 'tls'))
            stack.enter_context(patch.object(installer, 'select_agent', return_value=('zabbix-agent2.service', 'zabbix_agent2', str(config))))
            stack.enter_context(patch.object(installer.os, 'geteuid', return_value=0))
            stack.enter_context(patch.object(installer.os, 'chown'))
            stack.enter_context(patch.object(installer.shutil, 'which', return_value='/usr/bin/zabbix_agent2'))
            stack.enter_context(patch.object(installer.grp, 'getgrnam', return_value=argparse.Namespace(gr_gid=1000)))
            run = stack.enter_context(patch.object(installer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)))
            stack.enter_context(patch.object(sys, 'argv', ['installer', '--host', 'site1-pc1', '--key', str(key), '--active', '192.168.1.10:10051']))
            installer.main()
            text = config.read_text()
            self.assertNotRegex(text, r'(?m)^Server=')
            self.assertIn('ServerActive=192.168.1.10:10051', text)
            self.assertIn('TLSAccept=psk', text)
            self.assertEqual(run.call_args_list[0].args[0][1], '-T')
            self.assertEqual(run.call_args_list[1].args[0][:2], ['systemctl', 'restart'])

    def test_agent_autodetection_refuses_two_active_services(self):
        with patch.object(installer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaises(SystemExit):
                installer.select_agent("auto")


    def test_agent2_autodetection(self):
        with patch.object(installer.subprocess, "run", side_effect=[subprocess.CompletedProcess([], 3), subprocess.CompletedProcess([], 0)]):
            self.assertEqual(installer.select_agent("auto")[1], "zabbix_agent2")


    def test_setting_update_handles_spaces_and_is_idempotent(self):
        text = "# TLSAccept=unencrypted\nTLSAccept = unencrypted\nHostname=old\n"
        new = installer.update_setting(text, "TLSAccept", "psk")
        self.assertIn("\nTLSAccept=psk\n", new)
        self.assertEqual(installer.update_setting(new, "TLSAccept", "psk"), new)


    def test_failed_agent_validation_restores_original_without_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "agent.conf"
            original = "Server=127.0.0.1\nHostname=old\n"
            config.write_text(original)
            key = root / "key.psk"
            key.write_text("ab" * 32 + "\n")
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(installer, "TLS_DIRECTORY", root / "tls"))
                stack.enter_context(patch.object(installer, "select_agent", return_value=("zabbix-agent.service", "zabbix_agentd", str(config))))
                stack.enter_context(patch.object(installer.os, "geteuid", return_value=0))
                stack.enter_context(patch.object(installer.os, "chown"))
                stack.enter_context(patch.object(installer.shutil, "which", return_value="/usr/bin/zabbix_agentd"))
                stack.enter_context(patch.object(installer.grp, "getgrnam", return_value=argparse.Namespace(gr_gid=1000)))
                run = stack.enter_context(patch.object(installer.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)))
                stack.enter_context(patch.object(sys, "argv", ["installer", "--host", "PC", "--key", str(key), "--server", "192.0.2.1"]))
                with self.assertRaisesRegex(SystemExit, "validation failed"):
                    installer.main()
            self.assertEqual(config.read_text(), original)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][1], "-T")
            self.assertEqual(len(list(root.glob("agent.conf.before-zabbix-psk-*"))), 1)


if __name__ == "__main__":
    unittest.main()
