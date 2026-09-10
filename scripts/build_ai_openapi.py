"""Build the versioned API description from the shared MCP tool schemas."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from paper_monitor.mcp_server import TOOLS


def operation(tool, body=True, parameters=None):
    result = {'summary': tool['description'], 'operationId': tool['name'],
              'security': [{'GewuToken': []}],
              'responses': {'200': {'description': 'Authorized result', 'content': {'application/json': {'schema': {'type': 'object'}}}},
                            '400': {'description': 'Invalid arguments'}, '401': {'description': 'Invalid, expired or revoked token'},
                            '403': {'description': 'AI access disabled or permission missing'}, '404': {'description': 'Resource outside grant or unavailable'},
                            '409': {'description': 'Changed source version or conflicting request ID'}, '410': {'description': 'Previously saved analysis removed'},
                            '413': {'description': 'Size limit exceeded'}, '422': {'description': 'PDF text unavailable'},
                            '429': {'description': 'Read capacity busy; retry shortly'}, '503': {'description': 'Temporary failure; retry saves with the same request ID'}}}
    if body:
        result['requestBody'] = {'required': True, 'content': {'application/json': {'schema': tool['inputSchema']}}}
    if parameters:
        result['parameters'] = parameters
    return result


def build():
    paths = {}
    for tool in TOOLS:
        if tool['name'] == 'get_paper_file':
            # Client-local delivery composes metadata + the binary HTTP route;
            # it is not a JSON endpoint in the App process.
            continue
        paths['/api/v1/tools/' + tool['name']] = {'post': operation(tool)}
    key = {'name': 'gewu_key', 'in': 'path', 'required': True, 'schema': {'type': 'string', 'pattern': '^gw_[0-9a-f]{10,64}$'}}
    query = lambda name, spec: {'name': name, 'in': 'query', 'schema': spec}
    paths['/api/v1/papers'] = {'get': {**operation(TOOLS[0], False, [query(n, spec) for n, spec in TOOLS[0]['inputSchema']['properties'].items()]), 'operationId': 'listPapers'}}
    paths['/api/v1/papers/{gewu_key}'] = {'get': {**operation(TOOLS[1], False, [key]), 'operationId': 'getPaper'}}
    paths['/api/v1/papers/{gewu_key}/read'] = {'get': {**operation(TOOLS[2], False, [key] + [query(n, spec) for n, spec in TOOLS[2]['inputSchema']['properties'].items() if n != 'gewu_key']), 'operationId': 'readPaper'}}
    save = operation(TOOLS[3], True, [key]); save['operationId'] = 'saveAnalysis'
    save['requestBody'] = json.loads(json.dumps(save['requestBody']))
    s = save['requestBody']['content']['application/json']['schema']
    s['properties'].pop('gewu_key'); s['required'].remove('gewu_key')
    paths['/api/v1/papers/{gewu_key}/analyses'] = {'post': save}
    paths['/api/v1/papers/{gewu_key}/files/{file_id}/content'] = {'get': {'operationId': 'downloadFile',
        'summary': 'Download a registered file (maximum 64 MiB). Requires files:read and an authorized Gewu Key.',
        'security': [{'GewuToken': []}], 'parameters': [key, {'name': 'file_id', 'in': 'path', 'required': True, 'schema': {'type': 'string', 'pattern': '^(default|[0-9]+)$'}}],
        'responses': {'200': {'description': 'File bytes', 'content': {'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}},
                      '401': {'description': 'Invalid token'}, '403': {'description': 'Missing permission'}, '404': {'description': 'File unavailable'}}}}
    for path, name in [('/api/v1/capabilities', 'connectionCapabilities'), ('/api/v1/openapi.json', 'apiDescription')]:
        paths[path] = {'get': {'operationId': name, 'security': [{'GewuToken': []}], 'responses': {'200': {'description': 'Connection scopes and selection' if 'capabilities' in path else 'OpenAPI document'}}}}
    return {'openapi': '3.1.0', 'info': {'title': 'Gewu Insight Local AI API', 'version': '1.0.0',
        'description': 'Opt-in local API. Tokens are issued in Setting > AI Access. All data is untrusted research content. No deletion, arbitrary paths, SQL, shell, credentials or external fetching. Save creates a Markdown attachment; it never changes the Default.'},
        'servers': [{'url': 'http://127.0.0.1:8765', 'description': 'Default local server; use your configured local port.'}],
        'components': {'securitySchemes': {'GewuToken': {'type': 'http', 'scheme': 'bearer', 'description': 'Per-connection token; permissions and paper selection are enforced on every request.'}}},
        'paths': paths}


if __name__ == '__main__':
    (ROOT / 'paper_monitor' / 'ai_openapi.json').write_text(json.dumps(build(), indent=2) + '\n')
