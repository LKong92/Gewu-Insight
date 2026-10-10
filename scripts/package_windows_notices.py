"""Stage Gewu's notice documents; component-specific runtime notices stay separate."""
from pathlib import Path
import argparse
import shutil


DOCUMENTS = (
    "LICENSE",
    "CONTRIBUTING.md",
    "THIRD_PARTY_NOTICES.md",
    "docs/LICENSING.md",
    "docs/DEPENDENCY_LICENSE_AUDIT.md",
    "docs/RELEASE_COMPONENT_AUDIT.md",
)


def copy_notices(root: Path, output: Path) -> None:
    # Check the entire document set before copying a partial set into a payload.
    for relative in DOCUMENTS:
        if not (root / relative).is_file():
            raise FileNotFoundError(f"Missing package notice: {relative}")
    for relative in DOCUMENTS:
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    copy_notices(Path(__file__).resolve().parents[1], args.output)


if __name__ == "__main__":
    main()
