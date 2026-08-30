#!/usr/bin/env python3
"""Build a self-contained, offline Gewu Insight profile for documentation.

The generated profile never reads from the user's production database or data
directories.  Launch the UI with the printed environment variables to keep
SQLite, visible files, caches, portraits, and associated files together under
one disposable root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


DEMO_DATE = "2026-08-28"


def safe_profile_root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if root in {Path("/").resolve(), Path.home().resolve()} or len(root.parts) < 4:
        raise ValueError("Choose a dedicated profile directory, not a broad filesystem root")
    production = (Path(__file__).resolve().parents[1] / "data").resolve()
    if root == production or production in root.parents:
        raise ValueError("The documentation profile cannot live inside the production data directory")
    return root


def demo_pdf(path: Path, *, title: str, authors: str, accent: str = "#235EA7") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    pdf.setFillColor(HexColor(accent))
    pdf.rect(0, height - 96, width, 96, fill=1, stroke=0)
    pdf.setFillColorRGB(1, 1, 1)
    pdf.setFont("Helvetica-Bold", 18)
    words = title.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if pdf.stringWidth(candidate, "Helvetica-Bold", 18) > width - 84 and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    y = height - 42
    for line in lines[:3]:
        pdf.drawString(42, y, line)
        y -= 22
    pdf.setFillColorRGB(0.12, 0.15, 0.22)
    pdf.setFont("Helvetica", 11)
    pdf.drawString(42, height - 128, authors)
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(42, height - 178, "Abstract")
    pdf.setFont("Helvetica", 10.5)
    body = (
        "This offline demonstration document is included only in the Gewu Insight "
        "documentation profile. It shows how a paper, its current file, and related "
        "versions remain connected without using a real research library."
    )
    text = pdf.beginText(42, height - 202)
    text.setLeading(15)
    line = ""
    for word in body.split():
        candidate = f"{line} {word}".strip()
        if pdf.stringWidth(candidate, "Helvetica", 10.5) > width - 84 and line:
            text.textLine(line)
            line = word
        else:
            line = candidate
    if line:
        text.textLine(line)
    pdf.drawText(text)
    pdf.setStrokeColor(HexColor("#D7E1EC"))
    pdf.line(42, height - 290, width - 42, height - 290)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(42, height - 325, "1. A persistent paper object")
    pdf.setFont("Helvetica", 10.5)
    pdf.drawString(42, height - 348, "Metadata, folders, files, and provenance meet at one SQLite identity.")
    pdf.showPage()
    pdf.setFillColorRGB(0.12, 0.15, 0.22)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(42, height - 60, "Notes and evidence")
    pdf.setFont("Helvetica", 10.5)
    for index, sentence in enumerate(
        [
            "A publication may have a published version and one or more historical preprints.",
            "Associated files remain linked when the visible paper moves between folders.",
            "The documentation profile contains no credentials and performs no automatic network fetches.",
        ],
        start=1,
    ):
        pdf.drawString(58, height - 92 - index * 24, f"{index}. {sentence}")
    pdf.save()


def avatar(path: Path, *, initials: str, color: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (256, 256), (242, 245, 249, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((16, 16, 240, 240), fill=color)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", 76)
    except OSError:
        font = ImageFont.load_default()
    box = draw.textbbox((0, 0), initials, font=font)
    draw.text(
        ((256 - (box[2] - box[0])) / 2, (256 - (box[3] - box[1])) / 2 - 5),
        initials,
        fill="white",
        font=font,
    )
    image.save(path)


def raw_metadata(authors: list[str], *, source: str, arxiv_id: str = "", categories: list[str] | None = None) -> dict:
    if source == "arxiv":
        return {
            "source": "arxiv",
            "authors": authors,
            "arxiv_id": arxiv_id,
            "versioned_arxiv_id": f"{arxiv_id}v1" if arxiv_id else "",
            "categories": categories or ["quant-ph"],
            "primary_category": (categories or ["quant-ph"])[0],
        }
    return {
        "author": [
            {"given": " ".join(name.split()[:-1]), "family": name.split()[-1]}
            for name in authors
        ]
    }


def add_paper(storage, payload: dict) -> str:
    storage.upsert_paper(payload)
    return str(payload["paper_id"])


def attach_version(storage, paper_id: str, path: Path, *, role: str, label: str, primary: bool = False) -> int:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    resource = storage.create_paper_resource(
        paper_id=paper_id,
        stored_path=str(path),
        display_name=path.name,
        file_role="publication_version",
        version_role=role,
        version_label=label,
        storage_mode="managed",
        sha256=digest,
        content_sha256=digest,
        added_via="documentation_profile",
        mime_type="application/pdf",
        kind="pdf",
    )
    resource_id = int(resource["id"])
    if primary:
        storage.conn.execute(
            """
            UPDATE papers
            SET main_pdf_path = ?, merged_pdf_path = ?, download_status = 'success',
                primary_resource_id = ?, preferred_resource_id = ?, size_bytes = ?
            WHERE paper_id = ?
            """,
            (str(path), str(path), resource_id, resource_id, path.stat().st_size, paper_id),
        )
        storage.conn.commit()
    return resource_id


def build_profile(profile_root: Path) -> Path:
    data_root = profile_root / "data"
    data_root.mkdir(parents=True, exist_ok=False)
    os.environ["GEWU_DATA_ROOT"] = str(data_root)
    os.environ["GEWU_DOCUMENTATION_MODE"] = "1"

    from paper_monitor.config import DEFAULT_DB_PATH
    from paper_monitor.storage import Storage
    from paper_monitor.time_utils import now_iso

    storage = Storage(DEFAULT_DB_PATH)
    try:
        journals = [
            "Nature",
            "Science",
            "Nature Physics",
            "Physical Review Letters",
            "Nature Communications",
            "Nano Letters",
        ]
        timestamp = now_iso()
        rows = []
        for order, name in enumerate(journals):
            rows.append((name.casefold(), name, "[]", None, "science", 1, "", 1, order, timestamp, timestamp))
        storage.conn.executemany(
            """
            INSERT INTO journal_subscriptions (
              journal_key, name, issns_json, openalex_source_id, section_policy,
              skip_landing_enrichment, logo_url, enabled, display_order, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        storage.conn.commit()

        library_folders: dict[str, dict] = {}
        for name in ["0. Quantum Materials", "1. Topological Matter", "2. Quantum Information", "3. Reading & Reviews"]:
            library_folders[name] = storage.create_library_folder(parent_id=1, name=name)
            (data_root / "Library" / name).mkdir(parents=True, exist_ok=True)
        subfolders = {
            "Superconducting Qubits": "2. Quantum Information",
            "Topological Phases": "1. Topological Matter",
            "Two-Dimensional Materials": "0. Quantum Materials",
        }
        for name, parent in subfolders.items():
            folder = storage.create_library_folder(parent_id=int(library_folders[parent]["id"]), name=name)
            library_folders[name] = folder
            (data_root / "Library" / parent / name).mkdir(parents=True, exist_ok=True)

        library_papers = [
            {
                "paper_id": "demo:qubit-review",
                "doi": "10.1103/RevModPhys.93.025005",
                "title": "Superconducting qubits: current state of play",
                "journal": "Reviews of Modern Physics",
                "publication_date": "2021-05-20",
                "abstract": "A concise map of superconducting circuits, coherence, control, and scalable architectures.",
                "url": "https://doi.org/10.1103/RevModPhys.93.025005",
                "source": "crossref",
                "type": "review-article",
                "publisher_section": "article",
                "section_allowed": True,
                "raw": raw_metadata(["Alexandre Blais", "Steven M. Girvin"], source="crossref"),
                "folder": "Superconducting Qubits",
            },
            {
                "paper_id": "demo:topological-insulator",
                "doi": "10.1103/RevModPhys.82.3045",
                "title": "Topological insulators and superconductors",
                "journal": "Reviews of Modern Physics",
                "publication_date": "2010-11-08",
                "abstract": "Topology organizes robust quantum phases through global properties of electronic wave functions.",
                "url": "https://doi.org/10.1103/RevModPhys.82.3045",
                "source": "crossref",
                "type": "review-article",
                "publisher_section": "article",
                "section_allowed": True,
                "raw": raw_metadata(["Xiao-Liang Qi", "Shou-Cheng Zhang"], source="crossref"),
                "folder": "Topological Phases",
            },
            {
                "paper_id": "demo:twisted-materials",
                "doi": "10.1038/s41586-018-0136-4",
                "title": "Correlated insulator behaviour at half-filling in magic-angle graphene superlattices",
                "journal": "Nature",
                "publication_date": "2018-03-05",
                "abstract": "A moiré superlattice reveals tunable correlated electronic states in two-dimensional materials.",
                "url": "https://doi.org/10.1038/s41586-018-0136-4",
                "source": "crossref",
                "type": "article",
                "publisher_section": "research article",
                "section_allowed": True,
                "raw": raw_metadata(["Yuan Cao", "Pablo Jarillo-Herrero"], source="crossref"),
                "folder": "Two-Dimensional Materials",
            },
            {
                "paper_id": "demo:quantum-computation",
                "doi": "10.1038/35005001",
                "title": "Quantum computation and quantum information",
                "journal": "Nature",
                "publication_date": "2000-03-16",
                "abstract": "Information processing takes a new form when the carrier obeys the laws of quantum mechanics.",
                "url": "https://doi.org/10.1038/35005001",
                "source": "crossref",
                "type": "review-article",
                "publisher_section": "review",
                "section_allowed": True,
                "raw": raw_metadata(["Michael A. Nielsen", "Isaac L. Chuang"], source="crossref"),
                "folder": "2. Quantum Information",
            },
        ]
        for index, item in enumerate(library_papers):
            folder_name = item.pop("folder")
            paper_id = add_paper(storage, item)
            folder_id = int(library_folders[folder_name]["id"])
            storage.add_library_item(paper_id=paper_id, folder_id=folder_id)
            visible_dir = data_root / "Library"
            folder = storage.get_library_folder(folder_id) or {}
            parent = storage.get_library_folder(int(folder.get("parent_id") or 1)) or {}
            if int(folder.get("parent_id") or 1) == 1:
                visible_dir /= str(folder["name"])
            else:
                visible_dir = visible_dir / str(parent["name"]) / str(folder["name"])
            main = visible_dir / f"{paper_id.split(':')[-1].replace('-', '_')}.pdf"
            demo_pdf(main, title=item["title"], authors=", ".join(name for name in ["Researcher A", "Researcher B"]))
            attach_version(storage, paper_id, main, role="version_of_record", label="Published version", primary=True)
            if index == 0:
                associated = data_root / "Associated Files" / "Library" / "2. Quantum Information" / "Superconducting Qubits" / "qubit_review_preprint.pdf"
                demo_pdf(associated, title=item["title"] + " — preprint", authors="Researcher A, Researcher B", accent="#7667D7")
                attach_version(storage, paper_id, associated, role="preprint", label="Preprint v1")

        storage.set_setting(
            "library_shortcut_tabs",
            json.dumps(
                [
                    {"tab_id": "demo-shortcut-quantum", "folder_id": int(library_folders["2. Quantum Information"]["id"]), "label": "Quantum"},
                    {"tab_id": "demo-shortcut-topology", "folder_id": int(library_folders["1. Topological Matter"]["id"]), "label": "Topology"},
                ]
            ),
        )

        workspace = storage.create_library_root_folder(name="Seminar Notes")
        workspace_folder = storage.create_library_folder(parent_id=int(workspace["id"]), name="Foundational Papers")
        (data_root / "Spaces" / "Seminar Notes" / "Foundational Papers").mkdir(parents=True, exist_ok=True)
        storage.add_library_item(paper_id="demo:quantum-computation", folder_id=int(workspace_folder["id"]))
        storage.set_setting(
            "library_workspace_tabs",
            json.dumps([{"tab_id": f"space-{workspace['id']}", "label": "Seminar", "root_folder_id": int(workspace["id"])}]),
        )

        publications = [
            ("einstein:1905-photoelectric", "On a heuristic viewpoint concerning the production and transformation of light", "Annalen der Physik", "1905-03-18"),
            ("einstein:1905-brownian", "On the movement of small particles suspended in stationary liquids required by the molecular-kinetic theory of heat", "Annalen der Physik", "1905-05-11"),
            ("einstein:1905-relativity", "On the electrodynamics of moving bodies", "Annalen der Physik", "1905-06-30"),
            ("einstein:1916-gr", "The foundation of the general theory of relativity", "Annalen der Physik", "1916-03-20"),
        ]
        for order, (paper_id, title, journal, published) in enumerate(publications):
            add_paper(
                storage,
                {
                    "paper_id": paper_id,
                    "title": title,
                    "journal": journal,
                    "publication_date": published,
                    "abstract": "Historical demonstration metadata for the isolated documentation profile.",
                    "url": "https://einsteinpapers.press.princeton.edu/",
                    "source": "historical_demo",
                    "type": "article",
                    "publisher_section": "article",
                    "section_allowed": True,
                    "raw": {"authors": ["Albert Einstein"], "citation_count": 1200 - order * 140},
                },
            )
            publication = storage.add_my_publication(paper_id=paper_id)
            storage.set_my_publication_roles(
                publication_id=int(publication["id"]),
                first_author=True,
                corresponding_author=True,
            )

        author_profiles = [
            ("albert-einstein", "Albert Einstein", "Institute for Advanced Study", "AE", "#4263A8"),
            ("marie-curie", "Marie Curie", "Sorbonne University", "MC", "#8A5EA8"),
            ("emmy-noether", "Emmy Noether", "University of Göttingen", "EN", "#2A7D70"),
            ("richard-feynman", "Richard P. Feynman", "California Institute of Technology", "RF", "#C26B3C"),
        ]
        for source_id, name, affiliation, initials, color in author_profiles:
            portrait = data_root / "author_photos" / f"{source_id}.png"
            avatar(portrait, initials=initials, color=color)
            monitor = storage.add_author_monitor(
                {
                    "source_type": "historical",
                    "source_author_id": source_id,
                    "user_id": source_id,
                    "name": name,
                    "affiliation": affiliation,
                    "url": f"https://www.wikidata.org/wiki/Special:Search?search={name.replace(' ', '+')}",
                    "profile_url": f"https://www.wikidata.org/wiki/Special:Search?search={name.replace(' ', '+')}",
                    "interests": ["theoretical physics", "quantum theory"],
                }
            )
            storage.set_author_monitor_avatar_override(int(monitor["id"]), str(portrait))
            storage.update_author_monitor(
                int(monitor["id"]),
                status="success",
                message="Documentation profile — offline historical metadata.",
            )
        for monitor in storage.list_author_monitors():
            storage.add_author_monitor_paper(
                author_monitor_id=int(monitor["id"]),
                paper_id="einstein:1905-relativity",
                scholar_title="On the electrodynamics of moving bodies",
            )

        monitor_papers = [
            ("monitor:nature-quantum", "A programmable neutral-atom quantum processor", "Nature", "10.1038/s41586-026-10001-1", ["M. Example", "R. Scientist"], "quantum processor neutral atom"),
            ("monitor:nature-2d", "Emergent topology in a tunable moiré quantum material", "Nature", "10.1038/s41586-026-10002-2", ["L. Example", "T. Researcher"], "moire topology quantum material"),
            ("monitor:science-sensor", "Quantum-enhanced sensing with a solid-state spin network", "Science", "10.1126/science.demo001", ["A. Curie", "E. Noether"], "quantum sensing solid state spin"),
            ("monitor:nphys-circuit", "Coherent control across a superconducting circuit lattice", "Nature Physics", "10.1038/s41567-026-03001-3", ["R. Feynman", "Q. Engineer"], "superconducting circuit quantum control"),
            ("monitor:prl-edge", "Universal edge dynamics in a driven topological phase", "Physical Review Letters", "10.1103/PhysRevLett.136.010001", ["S. Zhang", "X. Qi"], "topological edge dynamics"),
            ("monitor:ncomms-memory", "Long-lived quantum memory in a layered material", "Nature Communications", "10.1038/s41467-026-50001-1", ["M. Curie", "D. Scholar"], "quantum memory layered material"),
            ("monitor:nano-device", "Atomic-scale control of a two-dimensional quantum device", "Nano Letters", "10.1021/acs.nanolett.6c00001", ["E. Noether", "P. Investigator"], "two dimensional quantum device"),
        ]
        journal_observations: dict[str, list[str]] = {name: [] for name in journals}
        for paper_id, title, journal, doi, authors, keywords in monitor_papers:
            add_paper(
                storage,
                {
                    "paper_id": paper_id,
                    "doi": doi,
                    "title": title,
                    "journal": journal,
                    "publication_date": DEMO_DATE,
                    "abstract": f"This documentation record illustrates {keywords} while preserving an offline, reproducible interface state.",
                    "url": f"https://doi.org/{doi}",
                    "source": "crossref",
                    "type": "article",
                    "publisher_section": "research article",
                    "section_allowed": True,
                    "raw": raw_metadata(authors, source="crossref"),
                },
            )
            journal_observations[journal].append(paper_id)
        for journal in journals:
            run_id = storage.start_fetch_run(
                monitor_type="journal",
                source="crossref",
                journal=journal,
                window_start=DEMO_DATE,
                window_end=DEMO_DATE,
                started_at=timestamp,
            )
            storage.record_journal_monitor_papers(
                fetch_run_id=run_id,
                observations=[{"paper_id": paper_id, "source": "crossref"} for paper_id in journal_observations[journal]],
            )
            storage.finish_fetch_run(run_id, status="success", records_found=len(journal_observations[journal]))

        subjects = [
            {"key": "quantum-computing", "name": "Quantum Computing", "queries": ["quantum processor", "quantum computation"]},
            {"key": "topological-matter", "name": "Topological Matter", "queries": ["topological phase", "topology"]},
            {"key": "quantum-sensing", "name": "Quantum Sensing", "queries": ["quantum sensing", "solid-state spin"]},
            {"key": "two-dimensional-materials", "name": "2D Materials", "queries": ["two-dimensional", "layered material", "moiré"]},
        ]
        storage.set_setting("theme_custom_groups", json.dumps(subjects))
        storage.set_setting("theme_group_order", json.dumps([subject["key"] for subject in subjects]))
        theme_map = {
            "quantum-computing": ["monitor:nature-quantum", "monitor:nphys-circuit"],
            "topological-matter": ["monitor:nature-2d", "monitor:prl-edge"],
            "quantum-sensing": ["monitor:science-sensor", "monitor:ncomms-memory"],
            "two-dimensional-materials": ["monitor:nature-2d", "monitor:nano-device"],
        }
        for subject in subjects:
            group_key = subject["key"].upper()
            for paper_id in theme_map[subject["key"]]:
                storage.record_theme_result(
                    paper_id=paper_id,
                    group_key=group_key,
                    group_name=subject["name"],
                    query=subject["queries"][0],
                    score=4,
                    hits=subject["queries"],
                    window_start=DEMO_DATE,
                    window_end=DEMO_DATE,
                )

        storage.set_setting("documentation_profile", "1")
        storage.set_setting("documentation_profile_date", DEMO_DATE)
    finally:
        storage.close()
    return data_root / "paper_monitor.sqlite"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-root", required=True, help="New, empty directory for the isolated profile")
    args = parser.parse_args()
    root = safe_profile_root(args.profile_root)
    if root.exists():
        raise SystemExit(f"Profile root already exists: {root}")
    root.mkdir(parents=True)
    db_path = build_profile(root)
    print(f"Documentation profile: {root}")
    print(f"SQLite: {db_path}")
    print(f"Launch: GEWU_DATA_ROOT={root / 'data'} GEWU_DOCUMENTATION_MODE=1 .venv/bin/python -m paper_monitor ui --port 8876")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
