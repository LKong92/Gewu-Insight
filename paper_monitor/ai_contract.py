"""Shared write contract; importing this module never starts network work."""
WRITE_SCOPES = {
    'create_space': 'spaces:create', 'create_folder': 'folders:create',
    'import_paper': 'papers:import', 'import_file': 'files:import',
    'add_paper_file': 'files:add', 'update_paper_metadata': 'metadata:write',
    'resolve_paper': 'papers:resolve', 'get_resolve_status': 'papers:resolve',
    'move_folder': 'folders:move', 'rename_folder': 'folders:rename',
    'move_file': 'files:move', 'rename_file': 'files:rename',
}
ORGANIZE_TOOLS = {'move_folder', 'rename_folder', 'move_file', 'rename_file'}
UPLOAD_SCOPES = ('papers:import', 'files:import', 'files:add')
REQUEST_ID = {'type': 'string', 'pattern': '^[a-zA-Z0-9_-]{8,100}$'}
METADATA_FIELDS = {
    'title': {'type': 'string', 'minLength': 1, 'maxLength': 2000},
    'authors': {'type': 'array', 'minItems': 1, 'maxItems': 1000, 'items': {'type': 'string', 'minLength': 1, 'maxLength': 300}},
    'publication_type': {'type': 'string', 'enum': ['journal_article', 'preprint', 'other']},
    'journal': {'type': 'string', 'minLength': 1, 'maxLength': 500},
    'publication_date': {'type': 'string', 'description': 'Known year, YYYY-MM or YYYY-MM-DD.'},
    'doi': {'type': ['string', 'null'], 'description': 'Known DOI, or null only when the source has no DOI. Unknown is missing metadata.'},
    'arxiv_id': {'type': ['string', 'null'], 'description': 'Known arXiv ID, or null when not an arXiv work.'},
    'source_url': {'type': 'string', 'description': 'HTTP(S) source the AI used for these facts; not fetched during import.'},
    'abstract': {'type': 'string', 'maxLength': 100000},
    'volume': {'type': 'string', 'maxLength': 100}, 'issue': {'type': 'string', 'maxLength': 100},
    'pages': {'type': 'string', 'maxLength': 200},
}
METADATA_REQUIRED = ['title', 'authors', 'publication_type', 'journal', 'publication_date', 'doi', 'arxiv_id', 'source_url']
