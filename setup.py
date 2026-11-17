#!/usr/bin/env python3
"""Interactive bootstrap for tubi16/zabbix-server and tubi16/zabbix-agent."""
import argparse
import ipaddress
import os
from pathlib import Path
import re
import shlex
import secrets
import shutil
import subprocess
import sys
import tempfile
import urllib.request


def run(*args, cwd=None, root=False):
    command = list(map(str, args))
    if root and os.geteuid() != 0:
        command.insert(0, "sudo")
    print("+", shlex.join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def ask(message):
    return input(message + " [e/H]: ").strip().lower() in {"e", "evet"}


def prompt(message, default='', validator=None):
    while True:
        value = input(message + (f' [{default}]' if default else '') + ': ').strip() or default
        try:
            if not value:
                raise ValueError('Bu alan gerekli.')
            if validator:
                validator(value)
            return value
        except (ValueError, argparse.ArgumentTypeError) as error:
            print('Geçersiz değer:', error)


def valid_selection(value):
    if value not in {'1', '2', '3'}:
        raise ValueError('1, 2 veya 3 seç.')


def valid_host(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', value):
        raise ValueError('1–64 harf, rakam, nokta, alt çizgi veya tire kullan.')


def enroll(target):
    print('Hedefte Python 3 ve Zabbix agent kurulu olmalı. PSK otomatik üretilir.')
    host = prompt('Cihazın Zabbix adı', validator=valid_host)
    address = prompt('Cihaz IP adresi', validator=ipaddress.ip_address)
    source = prompt('Zabbix sunucusunun agent tarafından görülen IP adresi', validator=ipaddress.ip_address)
    ssh = prompt('SSH kullanıcısı@cihaz veya SSH alias', default=address)
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@:-]*', ssh):
        raise ValueError('Geçersiz SSH hedefi.')
    agent_source = Path(prompt('Agent repo yolu', str(target.parent / 'zabbix-agent'))).expanduser().resolve()
    if not (agent_source / 'install.py').is_file():
        raise ValueError('Agent repo yolunda install.py bulunamadı.')
    command = [sys.executable, target / 'zabbix/tls/enroll.py', '--host', host,
               '--address', address, '--server', source, '--ssh', ssh,
               '--agent-source', agent_source]
    run(*command, '--plan', cwd=target)
    if ask('Bu cihaz kaydedilsin mi? Agent ayarları yedeklenir ve servisi yeniden başlatılır.'):
        run(*command, cwd=target)
        print('Geri alma: aynı kayıt komutuna --rollback ekle; agent için ilk config yedeğini kullan.')


def release():
    data = {}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            data[key] = value.strip('"\'')
    if data.get('ID') not in {'ubuntu', 'debian', 'arch'}:
        raise SystemExit('Desteklenen sistemler: Ubuntu, Debian, Arch Linux.')
    return data


def packages(distro, names):
    if not ask('Paket kurulacak: ' + ', '.join(names) + '. Devam edilsin mi?'):
        raise SystemExit('Paket kurulumu iptal edildi.')
    if distro == 'arch':
        run('pacman', '-S', '--needed', *names, root=True)
    else:
        run('apt-get', 'update', root=True)
        run('apt-get', 'install', *names, root=True)


def checkout(kind, base, distro):
    if not shutil.which('git'):
        packages(distro, ['git'])
    target = base / ('zabbix-' + kind)
    url = 'https://github.com/tubi16/zabbix-' + kind + '.git'
    if target.exists():
        if target.is_symlink() or not (target / '.git').is_dir():
            raise SystemExit('Hedef mevcut fakat bağımsız Git reposu değil: ' + str(target))
        origin = subprocess.check_output(['git', '-C', str(target), 'remote', 'get-url', 'origin'], text=True).strip()
        accepted = {url, url[:-4], 'git@github.com:tubi16/zabbix-' + kind + '.git'}
        if origin not in accepted:
            raise SystemExit('Mevcut reponun origin adresi beklenen repo ile eşleşmiyor.')
        print('Mevcut repo kullanılacak; yerel değişiklikler korunur, otomatik pull yapılmaz.')
    else:
        base.mkdir(parents=True, exist_ok=True)
        run('git', 'clone', '--', url, target)
    required = 'scripts/prepare_config.py' if kind == 'server' else 'install.py'
    if not (target / required).is_file():
        raise SystemExit('Gerekli dosya eksik: ' + required)
    return target


def server(target, distro, production=False):
    has_docker = bool(shutil.which('docker'))
    has_compose = has_docker and subprocess.run(['docker', 'compose', 'version'], capture_output=True).returncode == 0
    if not has_compose:
        if distro == 'arch':
            packages(distro, ['docker', 'docker-compose'])
        else:
            # Use an available distro package; never replace an existing engine.
            run('apt-get', 'update', root=True)
            compose = None
            for name in ('docker-compose-v2', 'docker-compose-plugin', 'docker-compose'):
                result = subprocess.run(['apt-cache', 'policy', name], capture_output=True, text=True, check=True, env={**os.environ, 'LC_ALL': 'C'})
                match = re.search(r'Candidate:\s+(\S+)', result.stdout)
                if match and match[1] != '(none)' and (name != 'docker-compose' or re.match(r'(?:\d+:)?[2-9]\.', match[1])):
                    compose = name
                    break
            if not compose:
                raise SystemExit('Compose v2 paketi bulunamadı. Docker resmi kurulumunu tamamlayıp tekrar çalıştır: https://docs.docker.com/engine/install/')
            packages(distro, ([ ] if has_docker else ['docker.io']) + [compose])
    run('docker', 'compose', 'version', root=True)
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'docker']).returncode != 0:
        if not ask('Docker servisi başlatılsın mı?'):
            raise SystemExit('Docker çalışır durumda olmalı.')
        run('systemctl', 'start', 'docker', root=True)
    run('docker', 'info', root=True)
    run(sys.executable, target / 'scripts/prepare_config.py', '--interactive', *(['--production'] if production else []))
    run('docker', 'compose', 'config', '--quiet', cwd=target, root=True)
    print('Ayarlar hazır. Port ve ağları .env içinde kontrol et. Parolalar ekrana yazılmaz.')
    if ask('Bu projenin servisleri docker compose up -d ile başlatılsın mı?'):
        run('docker', 'compose', 'up', '-d', cwd=target, root=True)
        run('docker', 'compose', 'ps', cwd=target, root=True)
        run(sys.executable, target / 'scripts/import_template.py', *(['--active'] if production else []))
    print('Devam: ' + str(target / 'docs/kurulum.md'))
    print('Durdurma (veri korunur): cd ' + shlex.quote(str(target)) + ' && sudo docker compose stop')


def install_agent(info):
    distro = info['ID']
    if shutil.which('zabbix_agent2'):
        return 'agent2'
    if shutil.which('zabbix_agentd'):
        return 'classic'
    if distro != 'arch':
        version = info.get('VERSION_ID', '')
        if not re.fullmatch(r'\d+(?:\.\d+)?', version):
            raise SystemExit('Dağıtım sürümü belirlenemedi.')
        url = (f'https://repo.zabbix.com/zabbix/7.4/release/{distro}/pool/main/z/zabbix-release/'
               f'zabbix-release_latest_7.4+{distro}{version}_all.deb')
        if not ask('Resmi Zabbix 7.4 paket deposu eklensin mi? Diğer Zabbix paketlerinin aday sürümleri de değişebilir.'):
            raise SystemExit('Depo kurulumu iptal edildi.')
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'zabbix-release.deb'
            urllib.request.urlretrieve(url, archive)
            archive.chmod(0o644)
            Path(temp).chmod(0o755)
            run('dpkg', '-i', archive, root=True)
    packages(distro, ['zabbix-agent2'])
    return 'agent2'


def valid_choice(value):
    if value not in {'1', '2'}:
        raise ValueError('1 veya 2 seç.')


def valid_port(value):
    if not value.isascii() or not value.isdigit() or not 1024 <= int(value) <= 32767:
        raise ValueError('1024–32767 arasında port gir.')


def valid_sources(value):
    for source in value.split(','):
        ipaddress.ip_network(source.strip(), strict=False)


def agent(target, info):
    print('Paket yöneticisi kurulum sırasında agent servisini başlatabilir.')
    choice = install_agent(info)
    host = prompt('Zabbix teknik host adı', validator=valid_host)
    mode = prompt('İzleme: 1) Pasif  2) Aktif (active-only)', '1', valid_choice)
    encryption = prompt('Bağlantı: 1) Şifreli (PSK)  2) Şifresiz', '1', valid_choice)
    command = [sys.executable, target / 'install.py', '--host', host, '--agent', choice]
    if mode == '1':
        address = prompt('Agent dinleme IP adresi (bu cihazın IP adresi; 0.0.0.0: tüm IPv4 arayüzleri)',
                         '0.0.0.0', ipaddress.ip_address)
        port = prompt('Agent dinleme portu', '10050', valid_port)
        sources = prompt('İzinli sunucu/proxy IP veya alt ağları (virgülle)', validator=valid_sources)
        command.extend(['--listen-ip', address, '--port', port])
        for source in sources.split(','):
            command.extend(['--server', source.strip()])
    else:
        address = prompt('Zabbix sunucu/proxy IP adresi', validator=ipaddress.ip_address)
        port = prompt('Zabbix sunucu/proxy portu', '10051', valid_port)
        endpoint = f'[{address}]:{port}' if ':' in address else f'{address}:{port}'
        command.extend(['--active', endpoint])
    if encryption == '1':
        key_input = input('PSK dosya yolu (boş: cihaza özel anahtar üret): ').strip()
        if key_input:
            key = Path(key_input).expanduser().resolve()
        else:
            private = target / 'private'
            if private.is_symlink():
                raise SystemExit('private sembolik bağlantı olamaz.')
            private.mkdir(mode=0o700, exist_ok=True)
            private.chmod(0o700)
            key = private / (host + '.psk')
            if key.is_symlink():
                raise SystemExit('PSK sembolik bağlantı olamaz.')
            if not key.exists():
                with os.fdopen(os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
                    stream.write(secrets.token_hex(32) + '\n')
            key.chmod(0o600)
            print('Cihaza özel PSK dosyası hazır:', key)
        if not key.is_file() or not re.fullmatch(r'[0-9a-fA-F]{64}', key.read_text().strip()):
            raise SystemExit('PSK dosyası 64 hexadecimal karakter içermeli.')
        command.extend(['--key', key, '--strict'])
    else:
        command.append('--unencrypted')
    print('Özet:', host, 'pasif' if mode == '1' else 'aktif', address, 'port', port,
          'PSK' if encryption == '1' else 'şifresiz')
    print('Zabbix template:', 'Essential Items Linux' if mode == '1' else 'Essential Items Linux Active')
    print('Host → Encryption →', 'Connections to host:' if mode == '1' else 'Connections from host:',
          'PSK; kimlik: zabbix-' + host if encryption == '1' else 'No encryption')
    if ask('Config yedeği alınarak ayarlar uygulansın ve agent servisi yeniden başlatılsın mı?'):
        run(*command, root=True)
        print('Geri alma: install.py çıktısındaki yedek ve komutu kullan; sunucu bağlantı ayarını da eşleştir.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--production', action='store_true', help='Yeni server kurulumunda sabit sürüm ve yerel yönetim portları')
    parser.add_argument('--directory', type=Path, default=Path.home() / 'zabbix-project', help='Repoların üst dizini')
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit('Normal kullanıcıyla çalıştır; gerekli komutlarda sudo sorulur.')
    if not sys.stdin.isatty():
        raise SystemExit('Etkileşimli terminal gerekli; önce dosyayı indir, sonra python3 setup.py çalıştır.')
    info = release()
    selection = prompt('İşlem: 1) Server kurulumu  2) Agent kurulumu  3) Sunucudan cihaz ekle', validator=valid_selection)
    if selection not in {'1', '2', '3'}:
        raise SystemExit('1 veya 2 seçilmeli.')
    kind = 'agent' if selection == '2' else 'server'
    local = Path(__file__).resolve().parent
    required = 'install.py' if kind == 'agent' else 'scripts/prepare_config.py'
    target = local if (local / required).is_file() else checkout(kind, args.directory.expanduser().resolve(), info['ID'])
    if selection == '3':
        enroll(target)
    elif kind == 'server':
        server(target, info['ID'], production=args.production)
    else:
        agent(target, info)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit('Kurulum durduruldu: ' + str(error))
    except (KeyboardInterrupt, EOFError):
        sys.exit('Kurulum iptal edildi; tamamlanan adımlar geri alınmadı.')
