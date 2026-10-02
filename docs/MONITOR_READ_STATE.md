# Discovery unread indicators

Journal Monitor and Subject Monitor acknowledge an unread paper when the user
selects that paper with the mouse or the Up/Down keys. Explicitly entering the
paper pane with the keyboard also acknowledges the selected paper. Loading a
date, opening a journal or subject, automatic first-card highlighting, changing
filters and refreshing a list do not acknowledge its papers.

The blue dot uses the existing late-arrival eligibility and per-paper read
records. Subject reports and searches project that same state. Selecting a paper
in either view updates its cached copies in both views. A journal or subject
retains its dot while any of its loaded papers remains unread, including papers
temporarily hidden by a display filter. Shared papers update all affected subject
dots. Author Monitor keeps its separate read state and explicit Read All action.

The server saves only the selected paper ID. The UI clears the dot after a
successful acknowledgement; failed or timed-out requests remain retryable.
Duplicate pending selections are coalesced, and a stale refresh response cannot
restore a dot already acknowledged in the current session. Metadata, figure and
download updates do not mark other papers as read. Sidebar late-arrival counts
and cached journal counts are reduced only for acknowledged papers.

The previous journal renderer scheduled every displayed unread paper to be
acknowledged after 1.4 seconds. That render-triggered batch operation is removed.
There is no schema migration or historical read-state reset: old records cannot
distinguish deliberate reading from the previous automatic acknowledgement.

Validation uses temporary SQLite and loopback HTTP in
`tests/test_monitor_unread_selection.py`, and the actual product renderers,
mouse/keyboard handlers and caches in `tests/monitor_unread_ui_probe.cjs` with
synthetic papers and intercepted acknowledgement requests.
