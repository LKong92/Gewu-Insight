#!/usr/bin/env python3
"""Pinned Sparkle build dependency. Never reads update signing private keys."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def prepare(app, cache):
    config = json.loads((ROOT / "config/macos-updates.json").read_text())
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / ("Sparkle-" + config["sparkle_version"] + ".tar.xz")
    if not archive.exists():
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as stream:
            pending = Path(stream.name)
            try:
                with urllib.request.urlopen(config["sparkle_url"], timeout=60) as response:
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
                stream.close()
                if hashlib.sha256(pending.read_bytes()).hexdigest() != config["sparkle_sha256"]:
                    raise ValueError("Sparkle download checksum mismatch")
                pending.replace(archive)
            finally:
                pending.unlink(missing_ok=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != config["sparkle_sha256"]:
        raise ValueError("Sparkle archive checksum mismatch")
    with tempfile.TemporaryDirectory(prefix="gewu-sparkle-", dir=cache) as directory:
        subprocess.run(["/usr/bin/tar", "-xf", str(archive), "-C", directory], check=True)
        framework = Path(directory) / "Sparkle.framework"
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(framework)], check=True)
        destination = app / "Contents/Frameworks/Sparkle.framework"
        if destination.exists():
            if not app.parent.name.startswith(".gewu-app-build."):
                raise ValueError("Replace frameworks only inside the native builder's staging App")
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["/usr/bin/ditto", str(framework), str(destination)], check=True)
        (app / "Contents/Resources/Sparkle-LICENSE.txt").write_bytes((Path(directory) / "LICENSE").read_bytes())
    info = app / "Contents/Info.plist"
    value = plistlib.loads(info.read_bytes())
    value.update(SUFeedURL=config["feed_url"], SUPublicEDKey=config["public_ed_key"],
                 SUEnableAutomaticChecks=True, SUScheduledCheckInterval=86400,
                 SUAutomaticallyUpdate=False, SUAllowsAutomaticUpdates=False,
                 SUEnableSystemProfiling=False, SUVerifyUpdateBeforeExtraction=True,
                 SURequireSignedFeed=True, SUSignedFeedFailureExpirationInterval=0)
    info.write_bytes(plistlib.dumps(value))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=ROOT / "tmp/macos-updater")
    args = parser.parse_args()
    prepare(args.app, args.cache)
