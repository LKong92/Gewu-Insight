#!/usr/bin/env python3
"""Build the Windows manual with the shared approved LaTeX layout."""
from __future__ import annotations
import argparse
import importlib.util
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]

def build(tex_output: Path, pdf_output: Path):
    spec = importlib.util.spec_from_file_location('gewu_shared_guide', ROOT / 'scripts/build_user_guide_pdf.py')
    common = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(common)
    common.HTML_SOURCE = ROOT / 'windows/Windows_Preview_Guide.html'
    soup = BeautifulSoup(common.HTML_SOURCE.read_text(encoding='utf-8'), 'html.parser')
    # Standalone HTML embeds image bytes; PDF uses the corresponding checked-in
    # image so the shared screenshot sizing and typesetting remain unchanged.
    for image in soup.select('img[data-pdf-image]'):
        path = (ROOT / image['data-pdf-image']).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError('Missing Windows guide image: ' + str(path))
        common.IMAGE_ROUTES[image['src']] = path
    original = common.latex_preamble
    def preamble(version, number):
        return original(version, number).replace('pdftitle={Gewu Insight User Guide}', f'pdftitle={{Gewu Insight User Guide - Windows {version}}}').replace(f'Version {version} (Build {number})', f'Windows {version} (Build {number})')
    common.latex_preamble = preamble
    common.build(tex_output, pdf_output)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tex-output', required=True, type=Path, help='Temporary generated TeX, outside tracked product files.')
    parser.add_argument('--pdf-output', default=ROOT / 'windows/Windows_Preview_Guide.pdf', type=Path)
    args = parser.parse_args()
    build(args.tex_output, args.pdf_output)
