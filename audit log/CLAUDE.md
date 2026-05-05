# Audit Log — CLAUDE.md

## What this is

A centralised audit log system for the Roxor Content HUB (Chairman Mao).  
Tracks who did what, when, and at what tier — across all tools and background tasks.

This subfolder (`audit log/`) is the self-contained home for everything audit-related:
routes, DB, templates, static files. Integrates into the hub via a registered blueprint.

---

## What needs tracking

### User actions
- Login / logout
- Tool access (which tool, which route, which action)
- Akeneo write operations (pushes, updates, attribute writes)
- Scaleflex uploads
- Brief creation, approval, rejection, send-back
- Cutout approve / deny
- Content tracker scan triggers
- Admin actions (user management, permission changes)

### Background / task events
- Akeneo batch upload jobs (start, progress, completion, errors)
- Any async task triggered by a user — logged with the triggering user's ID

---

## Access tiers

**TBD — Zach is defining tiers in a parallel terminal (2026-05-05).**

Once confirmed, document here:
- What each tier is called
- What they can see in the audit log (own actions only? team? all?)
- Whether any tier can export or clear logs

---

## Log entry shape (draft — confirm before building)

Each log entry should capture:

| Field | Notes |
|-------|-------|
| `id` | Auto-increment |
| `timestamp` | UTC |
| `user_id` | FK to hub.db users |
| `username` | Denormalised — preserved if user is later deleted |
| `tool` | `briefs`, `cutouts`, `content_tracker`, `linedrawings`, `admin`, `auth` |
| `action` | Short slug e.g. `brief.created`, `akeneo.push`, `login`, `cutout.approved` |
| `detail` | JSON blob — any extra context (SKU, brief ID, count pushed, error msg) |
| `ip_address` | From request |
| `tier` | User's access tier at time of action |
| `status` | `ok`, `error`, `partial` |

---

## Where audit data lives

- DB: `audit log/data/audit.db` — separate from hub.db and all tool DBs
- Single table: `audit_log`
- Never delete rows — soft audit trail only

---

## Integration points

- `shared/audit.py` — thin helper: `log_action(user_id, tool, action, detail=None, status='ok')`
- Called from within route handlers and task callbacks
- Blueprint registered in `app.py` as `/audit`
- View protected by auth + tier gating

---

## Blueprint plan (not built yet)

```
audit log/
├── CLAUDE.md           (this file)
├── __init__.py         (blueprint definition)
├── routes.py           (viewer routes)
├── data/
│   └── audit.db
├── templates/
│   └── audit/
│       └── index.html  (log viewer)
└── static/
    └── audit/
```

---

## Build order (agreed steps — update as we go)

- [ ] Confirm access tiers with Zach
- [ ] Build `shared/audit.py` helper
- [ ] Create `audit.db` + schema
- [ ] Register blueprint in `app.py`
- [ ] Build log viewer page (index.html)
- [ ] Wire `log_action()` into existing routes
- [ ] Wire into Akeneo task callbacks

---

## Notes

- Keep log writes fire-and-forget — never let a failed audit write block a user action
- Timestamps in UTC, display in local time in the UI
- `detail` JSON is for machine-readable context; `action` slug is for human-readable filtering

---

## Current status (2026-05-05)

**PAUSED** — Zach deploying the main Chairman Mao app for a trial run.  
Access tier structure being built in a parallel terminal — needed before any audit code is written.  
Resume point: confirm tiers → then start with `shared/audit.py` helper.
