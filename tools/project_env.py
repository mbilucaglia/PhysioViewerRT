"""Repository-relative setup, diagnostics and launch commands (stdlib only)."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / '.venv'
PYTHON = ENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
LOCK = ROOT / 'requirements-lock-windows-py312.txt'


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], cwd=ROOT, check=True, **kwargs)


def environment_info():
    if not PYTHON.is_file():
        raise RuntimeError('Missing .venv. Run setup first.')
    try:
        result = run([PYTHON, '-B', '-c',
                      'import sys,struct,json; print(json.dumps(dict('
                      'version=list(sys.version_info[:2]),bits=struct.calcsize("P")*8,'
                      'prefix=sys.prefix,executable=sys.executable)))'],
                     capture_output=True, text=True)
        info = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise RuntimeError('The local .venv cannot start. Do not copy a venv from another PC. '
                           'Preserve/rename it and recreate it with a local Python 3.12 x64.') from exc
    if Path(info['prefix']).resolve() != ENV.resolve():
        raise RuntimeError('Interpreter belongs to a different environment; recreate this .venv.')
    if info['version'] not in ([3, 11], [3, 12]) or info['bits'] != 64:
        raise RuntimeError('Use Python 3.11 or 3.12, 64-bit; Windows locked profile requires 3.12.')
    return info


def setup(profile):
    if not PYTHON.exists():
        if ENV.exists():
            raise RuntimeError('Incomplete .venv already exists. Preserve/rename it before setup.')
        if sys.version_info[:2] not in ((3, 11), (3, 12)) or sys.maxsize <= 2**32:
            raise RuntimeError('Create the environment using Python 3.11/3.12 x64.')
        venv.EnvBuilder(with_pip=True).create(ENV)
    info = environment_info()
    locked = profile == 'windows-py312' or (
        profile == 'auto' and os.name == 'nt' and info['version'] == [3, 12])
    if locked and (os.name != 'nt' or info['version'] != [3, 12]):
        raise RuntimeError('windows-py312 profile needs Windows and a Python 3.12 environment.')
    requirements = LOCK if locked else ROOT / 'requirements.txt'
    print(f'Installing {requirements.name} into {ENV}', flush=True)
    run([PYTHON, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', requirements])
    run([PYTHON, '-m', 'pip', 'check'])
    return doctor(gui=True)


def doctor(gui=False):
    info = environment_info()
    if Path(sys.prefix).resolve() != ENV.resolve():
        args = [PYTHON, '-B', Path(__file__).resolve(), 'doctor']
        if gui:
            args.append('--gui')
        return run(args).returncode
    modules = ['numpy', 'scipy', 'PySide6', 'pyqtgraph', 'vispy', 'OpenGL',
               'pylsl', 'pywt', 'meegkit', 'pyriemann', 'cvxeda', 'cvxopt']
    checks = []
    for module in modules:
        result = subprocess.run([sys.executable, '-B', '-c', f'import {module}'],
                                cwd=ROOT, capture_output=True, text=True, timeout=90)
        checks.append({'name': f'import {module}', 'ok': result.returncode == 0,
                       'detail': result.stderr[-2000:] if result.returncode else ''})
    pip = subprocess.run([sys.executable, '-m', 'pip', 'check'], cwd=ROOT,
                         capture_output=True, text=True, timeout=90)
    checks.append({'name': 'pip check', 'ok': pip.returncode == 0,
                   'detail': (pip.stdout + pip.stderr).strip()})
    if gui:
        child_env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
        code = ('from PySide6.QtWidgets import QApplication; '
                'from physiolab.gui import MainWindow; '
                'app=QApplication([]); w=MainWindow(); app.processEvents(); '
                'w.close(); app.processEvents(); print("MainWindow constructed")')
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT,
                                env=child_env, capture_output=True, text=True, timeout=90)
        checks.append({'name': 'Qt window (offscreen)', 'ok': result.returncode == 0,
                       'detail': (result.stdout + result.stderr)[-2000:]})
    versions = {d.metadata['Name']: d.version for d in importlib.metadata.distributions()
                if d.metadata.get('Name')}
    report = {'recorded_at': datetime.now(timezone.utc).isoformat(),
              'platform': platform.platform(), 'python': platform.python_version(),
              'repository': str(ROOT), 'environment': info, 'packages': versions,
              'checks': checks,
              'limitations': ['Offscreen validation does not verify native GPU rendering, '
                              'LSL network/firewall access or physical devices.']}
    report_dir = ROOT / '.local'
    report_dir.mkdir(exist_ok=True)
    (report_dir / 'environment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    for check in checks:
        print(f'{"OK" if check["ok"] else "FAIL"}: {check["name"]}')
        if not check['ok']:
            print(check['detail'])
    print(f'Local report: {report_dir / "environment.json"}')
    return 0 if all(c['ok'] for c in checks) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    install = sub.add_parser('setup')
    install.add_argument('--profile', choices=['auto', 'windows-py312', 'portable'], default='auto')
    install.add_argument('--non-interactive', action='store_true', help='For .cmd/setup callers')
    check = sub.add_parser('doctor')
    check.add_argument('--gui', action='store_true')
    sub.add_parser('run')
    sim = sub.add_parser('simulate')
    sim.add_argument('args', nargs=argparse.REMAINDER)
    tests = sub.add_parser('test')
    tests.add_argument('--gui', action='store_true')
    args = parser.parse_args()
    if args.command == 'setup':
        return setup(args.profile)
    if args.command == 'doctor':
        return doctor(args.gui)
    environment_info()
    if args.command == 'run':
        return run([PYTHON, '-B', ROOT / 'main.py']).returncode
    if args.command == 'simulate':
        rest = args.args[1:] if args.args[:1] == ['--'] else args.args
        return run([PYTHON, '-B', ROOT / 'simulate.py', *rest]).returncode
    child_env = dict(os.environ)
    if args.gui:
        child_env['QT_QPA_PLATFORM'] = 'offscreen'
    return run([PYTHON, '-B', '-m', 'unittest', 'discover', '-s',
                'tests_gui' if args.gui else 'tests', '-v'], env=child_env).returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f'Environment error: {exc}', file=sys.stderr)
        raise SystemExit(1)
