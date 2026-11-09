"""Opt-in TLS integration test; starts only a temporary loopback agent."""
import os
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import struct
import subprocess
import tempfile
import time
import unittest


def receive(sock, count):
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise EOFError("Connection closed")
        data += chunk
    return data


def ping(sock):
    payload = b"agent.ping"
    sock.sendall(b"ZBXD\x01" + struct.pack("<Q", len(payload)) + payload)
    header = receive(sock, 13)
    if header[:5] != b"ZBXD\x01":
        raise ValueError("Unexpected agent response")
    length = struct.unpack("<Q", header[5:])[0]
    if length > 65536:
        raise ValueError("Response too large")
    return receive(sock, length)


@unittest.skipUnless(os.getenv("RUN_TLS_INTEGRATION") == "1", "Set RUN_TLS_INTEGRATION=1 to start temporary loopback agent")
class RealTLSTest(unittest.TestCase):
    def test_psk_acceptance_wrong_key_and_plaintext_rejection(self):
        binary = shutil.which("zabbix_agentd")
        if not binary or not hasattr(ssl.SSLContext, "set_psk_client_callback"):
            self.skipTest("Requires classic agent and Python TLS PSK support")
        with tempfile.TemporaryDirectory(prefix="staj-tls-test-") as directory:
            root = Path(directory)
            key = secrets.token_hex(32)
            (root / "key.psk").write_text(key + "\n")
            (root / "key.psk").chmod(0o600)
            for attempt in range(30):
                port = 20000 + secrets.randbelow(10000)
                try:
                    with socket.socket() as address:
                        address.bind(("127.0.0.1", port))
                    break
                except OSError:
                    if attempt == 29:
                        self.fail("No free test port")
            config = root / "agent.conf"
            config.write_text(f"""LogType=console
PidFile={root / 'agent.pid'}
Server=127.0.0.1
ListenIP=127.0.0.1
ListenPort={port}
StartAgents=1
Hostname=Temporary-TLS-test
TLSAccept=psk
TLSPSKIdentity=test-identity
TLSPSKFile={root / 'key.psk'}
""")
            process = subprocess.Popen([binary, "-f", "-c", str(config)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 10
                while True:
                    if process.poll() is not None:
                        output = process.communicate()[0].decode(errors="replace").replace(key, "[redacted]")
                        self.fail("Temporary agent failed to start: " + output[-1500:])
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                            break
                    except OSError:
                        if time.monotonic() > deadline:
                            self.fail("Temporary agent did not listen")
                        time.sleep(0.05)

                def context(psk):
                    client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                    client.check_hostname = False
                    client.verify_mode = ssl.CERT_NONE  # PSK authentication; no certificates.
                    client.minimum_version = ssl.TLSVersion.TLSv1_2
                    client.maximum_version = ssl.TLSVersion.TLSv1_2
                    client.set_ciphers("PSK-AES128-GCM-SHA256")
                    client.set_psk_client_callback(lambda hint: ("test-identity", bytes.fromhex(psk)))
                    return client

                with socket.create_connection(("127.0.0.1", port), timeout=3) as raw:
                    with context(key).wrap_socket(raw) as encrypted:
                        self.assertEqual(ping(encrypted), b"1")
                with self.assertRaises((ssl.SSLError, OSError, EOFError)):
                    with socket.create_connection(("127.0.0.1", port), timeout=3) as raw:
                        with context(secrets.token_hex(32)).wrap_socket(raw) as encrypted:
                            ping(encrypted)
                with self.assertRaises((OSError, EOFError)):
                    with socket.create_connection(("127.0.0.1", port), timeout=3) as plain:
                        ping(plain)
            finally:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()


if __name__ == "__main__":
    unittest.main()
