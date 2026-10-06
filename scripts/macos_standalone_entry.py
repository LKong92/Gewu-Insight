"""Standalone startup: resolve an explicitly selected database before any writes."""
from pathlib import Path
import os
import sys


def main():
    resources = Path(__file__).resolve().parent
    project = resources / "project"
    sys.path[:0] = [str(project), str(resources / "dependencies")]
    from paper_monitor.workspace import read_locator, prepare_workspace, save_locator
    explicit = os.environ.get("GEWU_WORKSPACE_ROOT")
    remember = os.environ.get("GEWU_REMEMBER_DATABASE") == "1" or not explicit
    saved = read_locator() if remember else {}
    location = explicit or saved.get("workspace")
    if not location:
        raise RuntimeError("Open Gewu Insight.app to create or locate your Gewu Database.")
    workspace = Path(location).expanduser().resolve()
    os.environ["GEWU_WORKSPACE_ROOT"] = str(workspace)
    os.environ["GEWU_DATA_ROOT"] = str(workspace / "data")
    os.environ["GEWU_STANDALONE"] = "1"
    expected = os.environ.get("GEWU_DATABASE_UUID", "")
    if saved.get("workspace") == str(workspace):
        expected = saved.get("database_uuid", expected)
    create = os.environ.get("GEWU_CREATE_DATABASE") == "1"
    # A native server recovery after successful creation reopens that exact DB.
    if create and expected and (workspace / "data/paper_monitor.sqlite").is_file():
        create = False
    # Refuse a port collision before schema setup or automatic workers run.
    if 'ui' in sys.argv[1:]:
        import socket
        args = sys.argv[1:]
        port = int(args[args.index('--port') + 1]) if '--port' in args else 8765
        host = args[args.index('--host') + 1] if '--host' in args else '127.0.0.1'
        family = socket.AF_INET6 if ':' in host else socket.AF_INET
        with socket.socket(family) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, port))
            except OSError as error:
                raise RuntimeError('The local port is already in use. Quit the other Gewu App/server before opening this database.') from error
    identity = prepare_workspace(workspace, project, create=create, expected_identity=expected)
    if remember:
        save_locator(workspace, identity)
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.chdir(workspace)
    from paper_monitor.cli import main as cli_main
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
