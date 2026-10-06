#!/usr/bin/env python3
"""Build a private-test, self-contained DMG from an explicit Git revision.

Does not update the checkout, installed App, user data, or any Git branch.
Only a staging copy receives the standalone path adaptations. Supply verified
python-build-standalone archives, their matching license directories and pure
Python dependencies. No Developer ID, keychain access, or notarization is used.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile


HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MACHO = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
         b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def replace(path, before, after, count=1):
    source = path.read_text()
    if source.count(before) != count:
        raise RuntimeError(f"Upstream changed: {path.name}: expected {count} matches for {before!r}")
    path.write_text(source.replace(before, after))


def copy_tree(source, destination):
    shutil.copytree(source, destination, symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "macos-app-template.zip"))


def check_runtime_licenses(directory):
    def check(value):
        if isinstance(value, dict):
            for key, item in value.items():
                paths = [item] if key == "license_path" else item if key == "license_paths" else []
                for path in paths:
                    if not (directory / path).is_file():
                        raise RuntimeError(f"Missing runtime license: {directory / path}")
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)
    check(json.loads((directory / "PYTHON.json").read_text()))


def adapt_standalone_paths(source):
    """Keep assets/code immutable; place all writable paths outside the App."""
    # All writable paths are resolved by the shared workspace configuration.
    # Only isolated child-interpreter flags differ in the embedded runtime.
    ui = source / "paper_monitor/ui_server.py"
    replace(ui, '[sys.executable, "-c", script, function_name, term]',
            '[sys.executable, "-I", "-B", "-c", script, function_name, term]')
    replace(source / "paper_monitor/ai_service.py", '[sys.executable, str(Path(__file__).with_name(\'ai_pdf.py\'))',
            '[sys.executable, "-I", "-B", str(Path(__file__).with_name(\'ai_pdf.py\'))')
    replace(source / "paper_monitor/ai_http.py", "'args': [str(root / 'scripts' / 'gewu_mcp.py')]",
            "'args': ['-I', '-B', str(root / 'scripts' / 'gewu_mcp.py')]")
    return ["paper_monitor/ui_server.py", "paper_monitor/ai_service.py", "paper_monitor/ai_http.py"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--working-tree", action="store_true", help="Include local product changes and record their hashes; never include user data.")
    parser.add_argument("--inputs", type=Path, required=True,
                        help="Folder containing python-ARCH.tar.gz, licenses/ARCH and deps")
    parser.add_argument("--work", type=Path, required=True, help="Fresh output work directory")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    work, inputs, output = args.work.resolve(), args.inputs.resolve(), args.output.resolve()
    if work.exists() or output.exists():
        raise RuntimeError("Use a fresh work directory and output filename; existing outputs are preserved.")
    commit = subprocess.check_output(["git", "rev-parse", f"{args.ref}^{{commit}}"], cwd=REPO, text=True).strip()
    work.mkdir(parents=True)
    source = work / "source"
    source.mkdir()
    archive = work / "source.tar"
    with archive.open("wb") as stream:
        run("git", "archive", commit, cwd=REPO, stdout=stream)
    run("/usr/bin/tar", "-xf", archive, "-C", source)
    local_hashes = {}
    if args.working_tree:
        changed = subprocess.check_output(["git", "diff", "--name-only", commit], cwd=REPO, text=True).splitlines()
        changed += ["paper_monitor/workspace.py", "paper_monitor/database_migration.py", "scripts/GewuDatabaseLocation.h", "assets/macos-app-template.zip"]
        for name in sorted(set(changed)):
            path = REPO / name
            if not name.startswith(("paper_monitor/", "scripts/", "config/", "assets/", "docs/")):
                continue
            if path.is_file():
                (source / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, source / name)
                local_hashes[name] = sha256(path)
            elif (source / name).is_file():
                (source / name).unlink()
    adapted = adapt_standalone_paths(source)
    image_root = work / "image"
    image_root.mkdir()
    app = image_root / "Gewu Insight.app"
    env = dict(os.environ, GEWU_BUILD_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE="1")
    run("/bin/zsh", source / "scripts/build_macos_app.sh", "--output", app, env=env)
    resources = app / "Contents/Resources"
    project = resources / "project"
    project.mkdir()
    for name in ("paper_monitor", "config", "assets"):
        copy_tree(source / name, project / name)
    (project / "scripts").mkdir()
    shutil.copy2(source / "scripts/gewu_mcp.py", project / "scripts/gewu_mcp.py")
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", "requirements.txt"):
        shutil.copy2(source / name, project / name)
    copy_tree(inputs / "deps", resources / "dependencies")
    shutil.rmtree(resources / "dependencies/bin", ignore_errors=True)
    shutil.copy2(HERE / "macos_standalone_entry.py", resources / "macos_standalone_entry.py")
    server = app / "Contents/MacOS/Gewu Insight Server"
    shutil.copyfile(HERE / "macos_standalone_server.sh", server)
    server.chmod(0o755)
    lock = json.loads((inputs / "runtime-lock.json").read_text())
    for arch in ("arm64", "x86_64"):
        check_runtime_licenses(inputs / "licenses" / arch)
        runtime_archive = inputs / f"python-{arch}.tar.gz"
        if sha256(runtime_archive) != lock[arch]["sha256"]:
            raise RuntimeError(f"Runtime checksum mismatch: {arch}")
        runtime_stage = work / f"runtime-{arch}"
        runtime_stage.mkdir()
        # Reject archive paths escaping the dedicated extraction directory.
        with tarfile.open(runtime_archive) as stream:
            for member in stream.getmembers():
                target = runtime_stage / member.name
                if not target.resolve().is_relative_to(runtime_stage):
                    raise RuntimeError("Unsafe runtime archive path")
                if member.issym() and not (target.parent / member.linkname).resolve().is_relative_to(runtime_stage):
                    raise RuntimeError("Unsafe runtime symlink")
            stream.extractall(runtime_stage, filter="data")
        runtime = resources / "runtime" / arch
        runtime.parent.mkdir(exist_ok=True)
        copy_tree(runtime_stage / "python", runtime)
        # pip is a build-time tool; users never install dependencies at launch.
        site = runtime / "lib/python3.12/site-packages"
        for item in site.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        # PDF extraction and keyword discovery spawn sys.executable directly.
        # Relative site paths also work for those child processes and MCP,
        # without system Python, PYTHONPATH, or writing caches inside the App.
        (site / "gewu-standalone.pth").write_text(
            os.path.relpath(resources / "dependencies", site) + "\n" +
            os.path.relpath(project, site) + "\n" +
            "import sys; sys.dont_write_bytecode = True\n")
        for item in (runtime / "bin").iterdir():
            if not item.name.startswith("python"):
                item.unlink()
        copy_tree(inputs / "licenses" / arch, resources / "Runtime Licenses" / arch)
    dependencies = sorted(
        [{"name": dist.metadata["Name"], "version": dist.version,
          "license": dist.metadata.get("License-Expression") or dist.metadata.get("License", "See bundled license")}
         for dist in importlib.metadata.distributions(path=[str(inputs / "deps")])],
        key=lambda entry: entry["name"].lower())
    manifest = {"source_commit": commit, "architectures": ["arm64", "x86_64"],
                "minimum_macos": "14.0", "developer_id_signed": False, "notarized": False,
                "local_integrity_signature": "ad-hoc", "runtimes": lock,
                "dependencies": dependencies, "standalone_adapted_files": adapted,
                "workspace": "User-selected Gewu Database",
                "working_tree_files": local_hashes,
                "packaging_scripts": {name: sha256(HERE / name) for name in
                    ("package_macos_dmg.py", "macos_standalone_entry.py", "macos_standalone_server.sh")}}
    (resources / "Standalone Build.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (resources / "BUNDLED_RUNTIME_NOTICES.txt").write_text(
        "This private-test build bundles CPython from Astral python-build-standalone.\n"
        "See Runtime Licenses for exact build metadata and component license texts.\n"
        "Python dependencies, their readable source, license files and metadata are in dependencies/.\n"
        "certifi includes Mozilla's CA bundle under MPL-2.0; its source and license are included.\n"
        "Third-party components retain their own licenses; Gewu's research-use terms do not replace them.\n"
        "Optional LibreOffice and TeX installations are not bundled.\n")
    # Ensure no local research state or secrets entered the immutable bundle.
    for path in app.rglob("*"):
        if path.name in {".venv", ".git", ".gewu-workspace-token", "subjects.json"} or path.suffix in {".sqlite", ".sqlite3", ".db"}:
            raise RuntimeError(f"Unexpected local-state file: {path.relative_to(app)}")
    run("/usr/bin/xattr", "-cr", app)
    binaries = []
    for path in sorted(app.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as stream:
            if stream.read(4) in MACHO:
                binaries.append(path)
    main_binary = app / "Contents/MacOS/Gewu Insight"
    for path in [p for p in binaries if p != main_binary] + [server, app]:
        run("/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", path,
            stdout=subprocess.DEVNULL)
    for path in binaries + [app]:
        run("/usr/bin/codesign", "--verify", "--strict", path)
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", app)
    (image_root / "Applications").symlink_to("/Applications")
    instructions = f"""Gewu Insight — Private Mac Preview

1. Drag Gewu Insight.app to Applications.
2. Eject this disk image, then open Gewu Insight from Applications.
3. If macOS says the developer cannot be verified, review the source and then
   use System Settings > Privacy & Security > Open Anyway for this app.
   Do not disable Gatekeeper. A malware or damaged-app warning needs investigation.

Requires macOS 14 or later. Supports Apple Silicon and Intel.
Python and required dependencies are included. No Terminal or Python install is needed.
Internet access is required for online literature services, not for initial setup.
No Developer ID signature or Apple notarization. Local ad-hoc integrity signatures only.

On first launch, choose Create New Database or Open Existing Database.
Your selected Gewu Database folder contains data, reports, config and backups.
The saved location is kept in ~/Library/Application Support/Gewu Insight.
Logs are in ~/Library/Logs/Gewu Insight; browser data and caches remain in macOS Library.
Replacing the App does not replace these files. Removing the App retains your data.
The bundled User Guide describes the source-folder edition in its installation
section; follow this file for this standalone preview's installation and updates.
Optional Word conversion and TeX exports may require external tools.

Source: LKong92/Gewu-Insight, main commit {commit}
This preview adds only standalone packaging/path adapters to that source.
No personal research database, browser session, API key or AI access token is included.
"""
    (image_root / "Read Me.txt").write_text(instructions)
    shutil.copy2(source / "LICENSE", image_root / "LICENSE.txt")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_dmg = work / "Gewu-Insight.dmg"
    run("/usr/bin/hdiutil", "create", "-volname", "Gewu Insight", "-srcfolder", image_root,
        "-format", "UDZO", "-fs", "HFS+", temporary_dmg)
    run("/usr/bin/hdiutil", "verify", temporary_dmg)
    shutil.copy2(temporary_dmg, output)
    output.with_suffix(".dmg.sha256").write_text(f"{sha256(output)}  {output.name}\n")
    output.with_suffix(".build.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(output)


if __name__ == "__main__":
    main()
