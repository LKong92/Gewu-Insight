"""Real product server and STDIO MCP, disposable files/data, no online sources."""
import json
import os
from pathlib import Path
import subprocess
import sys
import zlib
import struct
from contextlib import ExitStack
from unittest.mock import patch
from tests.test_ai_writes import AIWriteTests
from paper_monitor import ui_server as ui
from paper_monitor.ai_contract import WRITE_SCOPES

fixture = AIWriteTests()
fixture.setUp()
try:
    with ExitStack() as patches:
        for name in ('refresh_pubmed_if_possible','refresh_semantic_scholar_if_possible','refresh_ads_if_possible'):
            patches.enter_context(patch.object(ui,name,return_value=None))
        patches.enter_context(patch.object(ui,'request_with_retries',side_effect=AssertionError('No external traffic')))
        token=fixture.enable_writes(scopes=['papers:read','folders:read','files:read','analysis:write',*set(WRITE_SCOPES.values())])
        pdf=fixture.root/'synthetic.pdf';pdf.write_bytes(fixture.pdf_bytes)
        png=fixture.root/'synthetic-figure.png'
        def chunk(kind,data): return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        png.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',48,32,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\x22\x77\xaa'*48)*32))+chunk(b'IEND',b''))
        for n in range(45):
            pid='scroll-'+str(n);fixture.storage.upsert_paper({'paper_id':pid,'title':'Synthetic row '+str(n),'journal':'Fixture','raw':{}});fixture.storage.add_library_item(paper_id=pid,folder_id=1)
        note=fixture.call('save_analysis',{'gewu_key':fixture.key,'title':'Original note','markdown':'# Original note\n\n'+('Text $x^2$.\n\n'*90),'request_id':'initial-note-001'})[1]
        file=fixture.root/'fixture.json'
        file.write_text(json.dumps({'url':f'http://127.0.0.1:{fixture.server.server_port}/','token':fixture.server.workspace_access.token,'mcp_token':token,
            'key':fixture.key,'pdf':str(pdf),'png':str(png),'note_id':note['file']['file_id'],
            'item_id':fixture.storage.conn.execute("SELECT id FROM library_items WHERE paper_id='one'").fetchone()[0]}))
        subprocess.run([sys.argv[1],'tests/library_live_ui_probe.cjs',str(file)],check=True,timeout=160)
finally:
    fixture.tearDown()
