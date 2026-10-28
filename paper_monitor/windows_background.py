"""Installed Windows service entry, shared by the App and Zotero companion.

The service owns the existing database leases. The App owns only its window
lease; closing its window may leave this service running for Zotero.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--app', required=True, type=Path)
    parser.add_argument('--host-pid', required=True, type=int)
    parser.add_argument('--port', default=0, type=int)
    args = parser.parse_args(argv)
    if not args.workspace.is_absolute() or not args.app.is_absolute() or args.host_pid <= 0 or not 0 <= args.port <= 65535:
        raise ValueError('Background startup requires an existing absolute workspace and App.')
    root = args.workspace.resolve(strict=True)
    os.environ.update(GEWU_WORKSPACE_ROOT=str(root), GEWU_DATA_ROOT=str(root / 'data'),
                      GEWU_APP_PATH=str(args.app), GEWU_DESKTOP_HOST=str(args.host_pid),
                      GEWU_SERVICE_HOST_PID=str(args.host_pid))
    from .windows_database import check_database, prepare, acquire_session, runtime_root
    from .zotero_integration import database_identity
    identity = database_identity(root / "data/paper_monitor.sqlite")
    os.environ["GEWU_RUNTIME_ROOT"] = str(runtime_root(root, identity))
    from .windows_service import live_status
    _, identity = check_database(root)
    if live_status(root, identity):
        return 0
    # No locator update and no empty replacement. Database leases remain exclusive.
    location = prepare(root, expected_identity=identity, desktop_owned=True)
    os.environ.update(GEWU_DATABASE_IDENTITY=identity, GEWU_RUNTIME_ROOT=location['runtime'])
    logs = Path(location['runtime']) / 'Logs'
    logs.mkdir(parents=True, exist_ok=True)
    log = (logs / 'windows-service.log').open('a', encoding='utf-8', buffering=1)
    previous_stdout, previous_stderr = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = log
    try:
        acquire_session(root / 'data/paper_monitor.sqlite', identity)
        from .cli import main as run
        return run(['--db', str(root / 'data/paper_monitor.sqlite'), 'ui', '--host', '127.0.0.1', '--port', str(args.port)])
    except Exception:
        import traceback
        traceback.print_exc()
        return 1
    finally:
        sys.stdout, sys.stderr = previous_stdout, previous_stderr
        log.close()


if __name__ == '__main__':
    raise SystemExit(main())
