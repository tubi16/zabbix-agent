"""Install a staged or strict PSK configuration for Linux agent or agent2."""
import argparse
from datetime import datetime, timezone
import grp
import glob
import ipaddress
import os
from pathlib import Path
import re
import shutil
import subprocess
def host_name(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
        raise argparse.ArgumentTypeError("Use 1–64 ASCII letters, digits, dots, underscores or hyphens")
    return value

TLS_DIRECTORY = Path("/etc/zabbix/tls")


def active_endpoint(value):
    """Accept a single DNS/IPv4/IPv6 endpoint, not agent config fragments."""
    match = re.fullmatch(r"(?:\[([0-9a-fA-F:]+)\]|([A-Za-z0-9][A-Za-z0-9.-]*)):(\d+)", value)
    if not match or not 1 <= int(match[3]) <= 65535:
        raise argparse.ArgumentTypeError("Use proxy.example.com:10051 or [IPv6]:10051")
    if match[1]:
        ipaddress.IPv6Address(match[1])
    return value


def update_setting(text, name, value):
    pattern = r"(?m)^\s*" + re.escape(name) + r"\s*=.*$"
    line = name + "=" + value
    if re.search(pattern, text):
        return re.sub(pattern, lambda match: line, text)
    return text.rstrip() + "\n" + line + "\n"


def select_agent(choice):
    agents = {"classic": ("zabbix-agent.service", "zabbix_agentd", "/etc/zabbix/zabbix_agentd.conf"),
              "agent2": ("zabbix-agent2.service", "zabbix_agent2", "/etc/zabbix/zabbix_agent2.conf")}
    if choice != "auto":
        return agents[choice]
    active = [value for value in agents.values()
              if subprocess.run(["systemctl", "is-active", "--quiet", value[0]],
                                capture_output=True).returncode == 0]
    if len(active) != 1:
        raise SystemExit("Expected exactly one running agent; specify --agent classic or --agent agent2")
    return active[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True, type=host_name)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--server", action="append", default=[], help="Additional allowed server IP/subnet; repeatable")
    parser.add_argument("--active", type=active_endpoint, help="Active-only destination: proxy IP/DNS:port; disables passive listener")
    parser.add_argument("--agent", choices=["auto", "classic", "agent2"], default="auto")
    parser.add_argument("--port", type=int, help="Agent listening port (1024–32767)")
    parser.add_argument("--strict", action="store_true", help="Reject unencrypted connections")
    args = parser.parse_args()
    if not args.server and not args.active:
        parser.error("Specify --server for passive checks or --active for active-only checks")
    if args.active and args.server:
        parser.error("--active is active-only; do not combine it with --server")
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo; never send your sudo password to anyone")
    for server in args.server:
        ipaddress.ip_network(server, strict=False)
    if args.port is not None and not 1024 <= args.port <= 32767:
        raise SystemExit("Agent port must be between 1024 and 32767")
    key = args.key.read_text().strip()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", key):
        raise SystemExit("Expected a 256-bit hexadecimal PSK")
    service, binary, filename = select_agent(args.agent)
    if shutil.which(binary) is None:
        raise SystemExit("Agent binary is not installed: " + binary)
    config = Path(filename)
    original = config.read_text()
    # Existing UserParameters may stay, but never silently override security
    # settings from another included file.
    for pattern in re.findall(r"(?m)^\s*Include=(.*)$", original):
        pattern = pattern.strip()
        if not os.path.isabs(pattern):
            pattern = str(config.parent / pattern)
        for included in glob.glob(pattern):
            if Path(included).is_dir():
                raise SystemExit("Directory Include found; inspect included configs before installing")
            content = Path(included).read_text()
            if re.search(r"(?m)^\s*(Include|Server|ServerActive|StartAgents|Hostname|TLS\w*)\s*=", content):
                raise SystemExit("Conflicting/nested agent settings found in " + included + "; inspect before installing")
    backup = config.with_name(config.name + ".before-staj-psk-" +
                              datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    shutil.copy2(config, backup)
    backup.chmod(0o600)
    directory = TLS_DIRECTORY
    directory.mkdir(mode=0o750, exist_ok=True)
    gid = grp.getgrnam("zabbix").gr_gid
    os.chown(directory, 0, gid)
    directory.chmod(0o750)
    target = directory / ("staj-" + args.host + ".psk")
    if target.is_symlink():
        raise SystemExit("Refusing a symlink as a PSK file")
    if target.exists() and target.read_text().strip() != key:
        raise SystemExit("Different existing PSK found; refusing to rotate it implicitly")
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    with os.fdopen(descriptor, "w") as file:
        file.write(key + "\n")
    os.chown(target, 0, gid)
    target.chmod(0o640)
    allowed = re.search(r"(?m)^\s*Server=(.*)$", original)
    servers = [s.strip() for s in allowed.group(1).split(",")] if allowed else []
    for server in args.server:
        if server not in servers:
            servers.append(server)
    already_strict = re.search(r"(?m)^\s*TLSAccept\s*=\s*psk\s*$", original) is not None
    settings = {"Server": ",".join(s for s in servers if s), "Hostname": args.host,
                "TLSPSKIdentity": "staj-" + args.host, "TLSPSKFile": str(target),
                "TLSConnect": "psk", "TLSAccept": "psk" if args.strict or already_strict else "unencrypted,psk"}
    if args.port is not None:
        settings["ListenPort"] = str(args.port)
    if args.active:
        # An absent Server disables passive checks in agent2; classic uses StartAgents.
        original_without_server = re.sub(r"(?m)^\s*Server\s*=.*$", "", original)
        settings.pop("Server")
        settings.update({"ServerActive": args.active, "TLSAccept": "psk"})
        if binary == "zabbix_agentd":
            settings["StartAgents"] = "0"
        original = original_without_server
    updated = original
    for name, value in settings.items():
        updated = update_setting(updated, name, value)
    config.write_text(updated)
    valid = subprocess.run([binary, "-T", "-c", str(config)], capture_output=True)
    if valid.returncode:
        shutil.copy2(backup, config)
        raise SystemExit("Configuration validation failed; original config restored; service not restarted")
    restarted = subprocess.run(["systemctl", "restart", service], capture_output=True)
    active = subprocess.run(["systemctl", "is-active", "--quiet", service])
    if restarted.returncode or active.returncode:
        shutil.copy2(backup, config)
        subprocess.run(["systemctl", "restart", service], capture_output=True)
        raise SystemExit("Restart failed; original configuration restored")
    print("Agent ready:", args.host, "strict PSK" if args.active or args.strict or already_strict else "PSK + temporary plaintext acceptance")
    print("Config backup:", backup)
    print("Rollback: sudo cp", backup, config, "&& sudo systemctl restart", service)


if __name__ == "__main__":
    main()
