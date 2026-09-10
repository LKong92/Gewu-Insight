# Author Monitor background work

Opening Author Monitor reuses the available in-memory list regardless of cache age. A cold scope uses the persistent card cache when ready, including live, author-scoped unread relationships. A cache being rebuilt retains the existing projection fallback. Local summary/index polling is separate from remote author checks; clicking tabs or changing scope never enqueues a Scholar request.

The status bar restores a durable publications/metadata summary after transient action messages expire. It distinguishes running work, retry waits, daily limits, failures and complete metadata. Empty automatic polls preserve the last meaningful daily author-check result. Background cards reconcile in place with retained controls, selected paper and reading anchor; details and native previews remain mounted. A background index must preserve the current selection over an older remembered one. After a metadata batch, cached detail data is invalidated for the next explicit selection without replacing an open editor.

## Scholar protection

All workspace HTTP requests bind their Scholar activity to the configured database. Background author refreshes and My Publications import steps bind the same context. The shared serialized request helper reads the persisted global cooldown before spacing and again immediately before sending. It detects access-restriction responses and persists the 24-hour circuit breaker before releasing the request lock, so already queued requests cannot slip through. A suppressed request does not extend the existing deadline. There is one network attempt per helper call; page and author pacing remain unchanged.

Preserved limits: request spacing 4–8 seconds; profile-page spacing 12–24 seconds; automatic author spacing 45–90 seconds; author-specific six-hour cooldown and global 24-hour pause. The daily scheduler starts checking due authors from 10:00 local time and normally reads the latest 50 publications; full citation-profile updates remain explicit. Manual actions and restarting do not bypass the persisted pause. The local 24-hour policy is not a Google unblock guarantee.

## Bounded metadata completion

`author_metadata_work.py` owns the automatic worker independently of tabs. It uses the existing DOI/arXiv/abstract resolver, not Google Scholar profile fetching. The canonical paper ID deduplicates shared authors. Newer papers are prioritized within each author's queue, and queues rotate so an empty first author does not block other authors.

Automatic limits are 20 papers per batch and 80 per local day. A worker checks its approximately two-minute time slice between papers, then rests at least five minutes. A single paper's bounded source calls may extend beyond the slice boundary. Existing seven-day retry markers are preserved. Explicit identifier commands use the same single worker slot but remain separate from the automatic daily budget; an explicit request waits for an active automatic slice rather than silently adding work beyond its reserved quota.

The existing SQLite app-settings table stores the daily reservation, rest deadline, author rotation and summary; no schema migration or new authority is introduced. Reservations are written before network work. Normal completion refunds unused slots; interruption conservatively retains the reservation until the day rolls over. A restart resumes only after the saved rest deadline. Failed/unresolved papers retain their attempt markers, while papers deferred by a time slice have no attempt marker. Metadata status exposes pending and retry-waiting counts instead of treating zero eligible papers as complete.

No automatic PDF download, file rewrite, Default change, Library-placement cleanup or AI connection change is added. Tests use temporary SQLite, synthetic metadata and mocked remote responses; UI probes use temporary Chrome pages.
