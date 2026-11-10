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
            self.assertEqual(len(list(root.glob("agent.conf.before-staj-psk-*"))), 1)


if __name__ == "__main__":
    unittest.main()
