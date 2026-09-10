"""Generate a disposable native acceptance Library without network access."""
from io import BytesIO
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
target = Path(sys.argv[1]).resolve()
target.relative_to(ROOT / "tmp")
db = target / "data/paper_monitor.sqlite"
if db.exists():
    raise SystemExit("Choose a fresh fixture workspace; existing databases are never overwritten.")
os.environ["GEWU_WORKSPACE_ROOT"] = str(target)
os.environ["GEWU_DATA_ROOT"] = str(target / "data")
sys.path.insert(0, str(ROOT))
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from paper_monitor.storage import Storage
from paper_monitor import ui_server as ui

storage = Storage(db)
try:
    ui.ensure_library_special_folders(storage)
    paper_id = "windows-reading-fixture"
    storage.upsert_paper({"paper_id":paper_id, "title":"Windows reading acceptance fixture", "journal":"Synthetic documents", "source":"fixture", "raw":{}})
    storage.add_library_item(paper_id=paper_id, folder_id=1)
    for title, count in [("A - short paper", 3), ("B - long paper", 240)]:
        writer = PdfWriter()
        font = writer._add_object(DictionaryObject({NameObject("/Type"):NameObject("/Font"), NameObject("/Subtype"):NameObject("/Type1"), NameObject("/BaseFont"):NameObject("/Helvetica")}))
        for n in range(count):
            page = writer.add_blank_page(width=612, height=792)
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):DictionaryObject({NameObject("/F1"):font})})
            lines = [f"BT /F1 22 Tf 48 735 Td ({title}) Tj ET", f"BT /F1 12 Tf 48 702 Td (Page {n+1} of {count}) Tj ET"]
            lines += [f"BT /F1 12 Tf 48 {660-i*20} Td (Line {i+1}: Synthetic keyboard reading fixture.) Tj ET" for i in range(23)]
            stream = DecodedStreamObject(); stream.set_data("\n".join(lines).encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(stream)
        content = BytesIO(); writer.write(content)
        ui.attach_file_to_paper(storage, paper_id=paper_id, filename=title+".pdf", content=content.getvalue(), file_role="other")
    for name, content in [("C - Reading note.md", b"# Reading note\n\n**Bold text** and a list:\n\n- First point\n- Second point"), ("D - Text.txt", b"Plain text reading fixture\nLine two")]:
        ui.attach_file_to_paper(storage, paper_id=paper_id, filename=name, content=content, file_role="other")
    content = BytesIO(); Image.new("RGB", (640,400), (40,90,150)).save(content, format="PNG")
    ui.attach_file_to_paper(storage, paper_id=paper_id, filename="E - Image.png", content=content.getvalue(), file_role="other")
finally:
    storage.close()
print(target)
