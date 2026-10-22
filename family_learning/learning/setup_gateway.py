#!/usr/bin/env python3
"""Install a stopped, parent-owned gateway; optionally accept a key privately.

Run as the desktop parent, never root. This does not enable child API traffic,
change DeepTutor, start services, or connect to OpenAI.
"""
import argparse
import getpass
import os
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
import tempfile


def private_dir(path):
    if path.is_symlink():
        raise ValueError('Refusing a linked configuration directory')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.stat()
    if info.st_uid != os.getuid() or not stat.S_ISDIR(info.st_mode):
        raise ValueError('Directory must belong to the signed-in parent')
    path.chmod(0o700)


def save_private(path, content):
    if path.is_symlink():
        raise ValueError('Refusing a linked credential or runtime file')
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--enter-api-key', action='store_true', help='Prompt privately for the dedicated project key')
    args = parser.parse_args()
    if os.getuid() == 0:
        raise SystemExit('Run as the desktop parent without sudo.')
    os.umask(0o077)
    home = Path.home()
    config = home / '.config/family-tutor'
    runtime = home / '.local/lib/family-tutor'
    state = home / '.local/state/family-tutor/budget'
    for directory in (config, runtime, state):
        private_dir(directory)
    token = config / 'gateway-token'
    if not token.exists():
        save_private(token, secrets.token_urlsafe(48) + '\n')
    # Validate an existing token rather than silently rotating a live client.
    from luna_gateway import private_text
    private_text(token)
    if args.enter_api_key:
        key = getpass.getpass('Dedicated Family Tutor OpenAI API key (hidden): ').strip()
        if not key.startswith('sk-') or len(key) < 30 or any(c.isspace() for c in key):
            raise SystemExit('Key format was not accepted; nothing was saved.')
        save_private(config / 'openai-api-key', key + '\n')
        del key
        print('API key saved privately. No provider request was made.')
    source = Path(__file__).resolve().parent
    for name in ('luna_gateway.py', 'weekly_budget.py'):
        save_private(runtime / name, (source / name).read_text())
    units = home / '.config/systemd/user'
    units.mkdir(parents=True, exist_ok=True)
    unit = units / 'family-tutor-gateway.service'
    expected = (source / 'family-tutor-gateway.service').read_text()
    if unit.exists() and unit.read_text() != expected:
        shutil.copy2(unit, config / ('gateway-service-backup-' + secrets.token_hex(4)))
    save_private(unit, expected)
    subprocess.run(['/usr/bin/systemctl', '--user', 'daemon-reload'], check=True)
    print('Gateway installed; no service was started or enabled.')
    print('Child API readiness was not changed. DeepTutor configuration was not changed.')


if __name__ == '__main__':
    main()
