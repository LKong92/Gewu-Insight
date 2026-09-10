"""SQLite state for resumable publication work and preserved Subject windows."""
from .publication_errors import public_import_message

# A source checkpoint remembers an explicit removal without retaining a paper.
# Ordinary resume must not silently restore it; an explicit full recheck may.
PUBLICATION_REMOVED_BY_USER = 'removed-by-user'


def ensure_workflow_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS subject_preserved_windows (
      group_key TEXT NOT NULL, window_start TEXT NOT NULL, window_end TEXT NOT NULL,
      PRIMARY KEY (group_key, window_start, window_end)
    );
    CREATE TABLE IF NOT EXISTS publication_import_jobs (
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL UNIQUE,
      profile_url TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'queued', page_offset INTEGER NOT NULL DEFAULT 0,
      page_signature TEXT NOT NULL DEFAULT '', seen INTEGER NOT NULL DEFAULT 0,
      added INTEGER NOT NULL DEFAULT 0, reused INTEGER NOT NULL DEFAULT 0,
      rejected INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
      updated_at TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS publication_import_items (
      job_id INTEGER NOT NULL REFERENCES publication_import_jobs(id) ON DELETE CASCADE,
      source_key TEXT NOT NULL, paper_id TEXT REFERENCES papers(paper_id) ON DELETE SET NULL,
      error TEXT NOT NULL DEFAULT '',
      PRIMARY KEY (job_id, source_key)
    );
    CREATE TABLE IF NOT EXISTS publication_identifier_tasks (
      publication_id INTEGER PRIMARY KEY REFERENCES my_publications(id) ON DELETE CASCADE,
      status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
      message TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_publication_identifier_status
      ON publication_identifier_tasks(status, publication_id);
    """)


def subject_revision(storage, key):
    return storage.get_setting('subject_edit_revision:' + key, '')


def subject_window_preserved(storage, key, start, end):
    return storage.conn.execute(
        'SELECT 1 FROM subject_preserved_windows WHERE group_key=? AND window_start=? AND window_end=?',
        (key, start, end),
    ).fetchone() is not None


def preserve_subject_history(storage, key, revision):
    """Editing protects all existing windows, including empty/partial fetches."""
    storage.conn.execute("""
        INSERT OR IGNORE INTO subject_preserved_windows
        SELECT group_key, window_start, window_end FROM theme_results WHERE group_key=?
        UNION SELECT ?, window_start, window_end FROM fetch_runs
        WHERE monitor_type='theme' AND journal=?
    """, (key, key, 'theme:' + key))
    storage.set_setting('subject_edit_revision:' + key, revision)


def publication_work_snapshot(storage):
    jobs = [dict(row) for row in storage.conn.execute(
        'SELECT * FROM publication_import_jobs ORDER BY id DESC')]
    saved = {row['job_id']: row['n'] for row in storage.conn.execute('''
        SELECT i.job_id, count(DISTINCT p.paper_id) AS n
        FROM publication_import_items i JOIN my_publications p ON p.paper_id=i.paper_id
        GROUP BY i.job_id
    ''')}
    for job in jobs:
        job['message'] = public_import_message(job['status'], job['message'])
        job['currently_saved'] = saved.get(job['id'], 0)
    counts = {row['status']: row['n'] for row in storage.conn.execute(
        'SELECT status, count(*) AS n FROM publication_identifier_tasks GROUP BY status')}
    return {'imports': jobs, 'identifiers': counts}
