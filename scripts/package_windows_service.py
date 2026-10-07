"""Assemble a signed CPython embedded runtime with an explicit product allowlist."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--runtime", required=True, type=Path)
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--reuse-service", type=Path, help="Reuse only verified dependencies; product source is always rebuilt.")
args = parser.parse_args()
output = args.output.resolve()
if output.exists():
    raise SystemExit("Service output must be a new directory")
shutil.copytree(args.runtime, output)
dependencies = output / "Lib" / "site-packages"
if args.reuse_service:
    from importlib.metadata import distributions
    source_dependencies = args.reuse_service / "Lib/site-packages"
    versions = {d.metadata['Name'].lower().replace('_', '-'): d.version for d in distributions(path=[str(source_dependencies)])}
    for requirement in (root / "windows/requirements.lock").read_text().splitlines():
        if not requirement.strip() or requirement.startswith('#'):
            continue
        name, version = requirement.strip().split('==')
        if versions.get(name.lower().replace('_', '-')) != version:
            raise SystemExit('Previously packaged dependency differs from requirements.lock: ' + name)
    shutil.copytree(source_dependencies, dependencies)
else:
    subprocess.run([sys.executable, "-m", "pip", "install", "--only-binary=:all:", "--no-compile",
                    "--target", str(dependencies), "-r", str(root / "windows" / "requirements.lock")], check=True)
source = output / "app"
source.mkdir()
for name in ("paper_monitor", "assets"):
    shutil.copytree(root / name, source / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
(source / "config").mkdir()
(source / "scripts").mkdir()
shutil.copy2(root / "scripts" / "gewu_mcp.py", source / "scripts" / "gewu_mcp.py")
shutil.copy2(root / "config" / "journals.json", source / "config" / "journals.json")
shutil.copy2(root / "windows" / "service_entry.py", output / "service_entry.py")
# No import site: disable user site-packages, environment and registry paths.
pth = next(output.glob("python*._pth"))
stdlib = next(output.glob("python3*.zip")).name
pth.write_text("\n".join([stdlib, ".", "app", "Lib/site-packages", "Lib/site-packages/win32",
                          "Lib/site-packages/win32/lib", "Lib/site-packages/pywin32_system32", ""]), encoding="utf-8")
print(output)
