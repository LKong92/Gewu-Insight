"""Versioned HTTP boundary and workspace-only connection management."""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .ai_service import WRITE_LOCK, execute, integer
from .ai_store import APIError, audit, authenticate, create_connection, fail, set_folder_access, set_write_access, settings_snapshot, utc_now
from .storage import Storage


def body(handler):
    try:
        size = int(handler.headers.get('Content-Length', '0'))
        if size < 0 or size > 1024 * 1024 or handler.headers.get('Transfer-Encoding'):
            fail(413, 'request_too_large', 'The request exceeds 1 MiB.')
        data = json.loads(handler.rfile.read(size))
    except (ValueError, UnicodeError):
        fail(400, 'invalid_json', 'Provide a valid JSON object.')
    if not isinstance(data, dict):
        fail(400, 'invalid_json', 'Provide a valid JSON object.')
    return data


def mcp_config(token, port):
    root = Path(__file__).resolve().parents[1]
    return {'mcpServers': {'gewu-insight': {'command': sys.executable,
            'args': [str(root / 'scripts' / 'gewu_mcp.py')],
            'env': {'GEWU_API_URL': f'http://127.0.0.1:{port}', 'GEWU_API_TOKEN': token}}}}


def handle_admin(handler):
    storage = Storage(handler.configured_db_path)
    try:
        created = {}
        if handler.command == 'POST':
            payload = body(handler)
            action = payload.get('action')
            with WRITE_LOCK:
                if action == 'enable':
                    if not isinstance(payload.get('enabled'), bool):
                        fail(400, 'invalid_enabled', 'Choose whether to enable AI access.')
                    storage.set_setting('ai_access_enabled', 'true' if payload['enabled'] else 'false')
                elif action == 'create':
                    created = create_connection(storage, payload)
                    created['mcp_config'] = mcp_config(created['token'], handler.server.server_port)
                elif action == 'revoke':
                    connection_id = integer(payload.get('connection_id'), 0, 1, 2**63 - 1)
                    cursor = storage.conn.execute('UPDATE ai_connections SET revoked_at=? WHERE id=? AND revoked_at IS NULL', (utc_now(), connection_id))
                    storage.conn.commit()
                    if not cursor.rowcount:
                        fail(404, 'connection_unavailable', 'This connection is already revoked or unavailable.')
                elif action == 'write_access':
                    connection_id = integer(payload.get('connection_id'), 0, 1, 2**63 - 1)
                    set_write_access(storage, connection_id, payload.get('scopes'), payload.get('write_folder_ids'))
                elif action == 'folder_access':
                    connection_id = integer(payload.get('connection_id'), 0, 1, 2**63 - 1)
                    set_folder_access(storage, connection_id, payload.get('allowed'))
                else:
                    fail(400, 'invalid_action', 'Choose a supported AI Access action.')
        handler.send_json({**settings_snapshot(storage), **created})
    except APIError as exc:
        handler.send_json({'error': str(exc), 'code': exc.code}, exc.status)
    except Exception:
        logging.getLogger(__name__).exception('AI connection management failed')
        handler.send_json({'error': 'AI Access could not be updated. Please retry.', 'code': 'unavailable'}, 503)
    finally:
        storage.close()


def handle_api(handler):
    storage = Storage(handler.configured_db_path)
    try:
        authorization = handler.headers.get('Authorization', '')
        authenticate(storage, authorization)
        parsed = urlparse(handler.path)
        path = parsed.path
        args = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        if path == '/api/v1/uploads' and handler.command == 'POST':
            from .ai_uploads import receive
            from urllib.parse import unquote
            try:
                length = int(handler.headers.get('Content-Length', '0'))
            except ValueError:
                fail(400, 'invalid_length', 'Provide a valid Content-Length.')
            if handler.headers.get('Transfer-Encoding'):
                fail(400, 'invalid_length', 'Provide a known file length.')
            handler.connection.settimeout(30)
            result = receive(storage, authorization, handler.rfile,
                name=unquote(handler.headers.get('X-Gewu-Filename', '')),
                length=length, digest=handler.headers.get('X-Gewu-SHA256', ''),
                retry_id=handler.headers.get('X-Gewu-Request-ID', ''))
            audit(storage,authenticate(storage,authorization),'upload_file')
            handler.send_json(result)
            return
        if path == '/api/v1/openapi.json' and handler.command == 'GET':
            handler.send_bytes(Path(__file__).with_name('ai_openapi.json').read_bytes(), content_type='application/json; charset=utf-8')
            return
        if path == '/api/v1/capabilities' and handler.command == 'GET':
            operation = 'capabilities'
        elif path == '/api/v1/papers' and handler.command == 'GET':
            operation = 'search_papers'
        elif path.startswith('/api/v1/tools/') and handler.command == 'POST':
            operation = path.removeprefix('/api/v1/tools/')
            args = body(handler)
        else:
            match = re.fullmatch(r'/api/v1/papers/(gw_[0-9a-f]{10,64})(?:/(read|analyses|files/(default|[0-9]+)/content))?', path)
            if not match:
                fail(404, 'unknown_route', 'This API route is not available.')
            key, action, file_id = match.groups()
            expected = 'POST' if action == 'analyses' else 'GET'
            if handler.command != expected:
                fail(405, 'method_not_allowed', f'Use {expected} for this operation.')
            if expected == 'POST':
                args = body(handler)
            args['gewu_key'] = key
            if file_id:
                args['file_id'] = file_id
            operation = 'download_file' if file_id else {'read': 'read_paper', 'analyses': 'save_analysis', None: 'get_paper'}[action]
        result = execute(storage, authorization, operation, args)
        if operation == 'download_file':
            file, content = result
            handler.send_response(200)
            handler.send_header('Content-Type', 'application/octet-stream')
            handler.send_header('Content-Disposition', 'attachment; filename="gewu-file"')
            handler.send_header('Content-Length', str(len(content)))
            handler.send_header('Cache-Control', 'no-store')
            handler.send_header('X-Content-Type-Options', 'nosniff')
            handler.end_headers()
            handler.wfile.write(content)
        else:
            handler.send_json(result)
    except APIError as exc:
        handler.send_json({'error': str(exc), 'code': exc.code}, exc.status)
    except (BrokenPipeError, ConnectionResetError):
        pass
    except Exception:
        logging.getLogger(__name__).exception('AI API operation failed')
        handler.send_json({'error': 'This operation could not finish. Retry writes with the same request ID and unchanged arguments.', 'code': 'unavailable'}, 503)
    finally:
        storage.close()
