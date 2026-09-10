"""Conservative PDF source eligibility shared with the Windows Browser shell.

Unknown hosts are unverified, not declared infringing. Add a host only after
checking its publisher/repository authority; never infer authorization from a
working PDF URL, a DOI in the bytes, an .edu suffix or an OA search label alone.
"""
from pathlib import Path
from urllib.parse import urlsplit

APPROVED_PDF_HOSTS = tuple(line.strip() for line in
                         Path(__file__).with_name("pdf_source_hosts.txt").read_text(encoding="utf-8").splitlines()
                         if line.strip() and not line.lstrip().startswith("#"))
UNVERIFIED_PDF_SOURCE = "PDF source is not verified as a publisher or authorized repository. Download stopped."


def approved_pdf_source(url: str) -> bool:
    try:
        value = urlsplit(str(url))
        host = (value.hostname or "").lower().rstrip(".")
        return (value.scheme in {"http", "https"} and not value.username and not value.password
                and value.port in {None, 80, 443}
                and any(host == domain or host.endswith("." + domain) for domain in APPROVED_PDF_HOSTS))
    except ValueError:
        return False
