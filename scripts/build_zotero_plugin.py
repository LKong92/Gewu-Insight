#!/usr/bin/env python3
"""Build the Zotero plugin without bundling credentials, user data or test files."""
import argparse
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main():
    root = Path(__file__).resolve().parents[1]
    source = root / "integrations" / "zotero"
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or root / "dist" / f"gewu-insight-zotero-{manifest['version']}.xpi"
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name in ("manifest.json", "bootstrap.js", "core.js", "ui.js", "monitor.js", "import.js", "actor-parent.mjs", "actor-child.mjs", "workspace.js", "pdf-preview.js", "pdf-resources.js", "browser.js", "web-parent.mjs", "web-child.mjs"):
            archive.write(source / name, name)
        workspace_script = (source / "workspace.js").read_text(encoding="utf-8") + "\n" + (source / "pdf-preview.js").read_text(encoding="utf-8")
        archive.writestr("workspace-source.js", "var GewuWorkspaceSource = " + json.dumps(workspace_script) + ";\n")
        archive.write(root / "assets/gewu-insight-app-icon.png", "icons/gewu.png")
        archive.write(root / "LICENSE", "LICENSE")
    print(output)


if __name__ == "__main__":
    main()
