#!/usr/bin/env python3
"""Create a signed Mac-only feed for an already verified Release installer.

Run after uploading the matching installer. This prepares the feed locally;
it neither publishes a Release nor uploads the feed. Signing uses Keychain.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"
ET.register_namespace("sparkle", NS)


def make_feed(manifest, installer, signature, notes):
    if (manifest.get("product") != "Gewu Insight"
            or not re.fullmatch(r"[0-9a-f]{40}", manifest.get("source_commit", ""))
            or set(manifest.get("architectures", [])) != {"arm64", "x86_64"}):
        raise ValueError("Use the verified universal Mac build manifest with its exact source commit")
    version = manifest["version"]
    build = str(manifest["build"])
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or not re.fullmatch(r"[1-9]\d*", build):
        raise ValueError("Stable Mac releases need a numeric version and increasing build")
    name = f"Gewu-Insight-macOS-{version}.dmg"
    if installer.name != name or manifest.get("installer", {}).get("name") != name:
        raise ValueError("Only the matching Mac installer can enter this feed")
    if hashlib.sha256(installer.read_bytes()).hexdigest() != manifest["installer"]["sha256"]:
        raise ValueError("Installer checksum differs from the verified build manifest")
    if manifest.get("working_tree_files"):
        raise ValueError("Publish a clean committed build, not a working-tree preview")
    root = ET.Element("rss", {"version":"2.0"})
    channel = ET.SubElement(root,"channel")
    ET.SubElement(channel,"title").text = "Gewu Insight for macOS"
    ET.SubElement(channel,"link").text = "https://github.com/LKong92/Gewu-Insight/releases"
    ET.SubElement(channel,"description").text = "Official stable Mac updates"
    item = ET.SubElement(channel,"item")
    ET.SubElement(item,"title").text = f"Gewu Insight {version}"
    ET.SubElement(item,f"{{{NS}}}version").text = build
    ET.SubElement(item,f"{{{NS}}}shortVersionString").text = version
    ET.SubElement(item,f"{{{NS}}}minimumSystemVersion").text = manifest["minimum_macos"]
    ET.SubElement(item,"description").text = notes
    ET.SubElement(item,"enclosure", {
        "url": f"https://github.com/LKong92/Gewu-Insight/releases/download/macos-{version}/{name}",
        "length": str(installer.stat().st_size), "type":"application/octet-stream",
        f"{{{NS}}}edSignature":signature, f"{{{NS}}}os":"macos",
    })
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer",type=Path,required=True)
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--notes",type=Path,required=True)
    parser.add_argument("--sparkle-bin",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    config=json.loads((ROOT/"config/macos-updates.json").read_text())
    command=[str(args.sparkle_bin/"sign_update"),"--account",config["keychain_account"]]
    signature=subprocess.check_output(command+["-p",str(args.installer)],text=True).strip()
    feed=make_feed(json.loads(args.manifest.read_text()),args.installer,signature,args.notes.read_text())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_bytes(feed)
    subprocess.run(command+[str(args.output)],check=True)
    subprocess.run(command+["--verify",str(args.output)],check=True)
    print(args.output)


if __name__=="__main__":main()
