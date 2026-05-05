# Line Drawings Tool — CLAUDE.md

## What this is
The Line Drawing Generator ported into the Roxor Content HUB (Chairman Mao).
This is ONE tool inside the hub — a Flask Blueprint, not a standalone app.

**Blueprint name**: `linedrawings`  
**URL prefix**: `/linedrawings`  
**Auth**: `@tool_access_required('linedrawings')` on every route — never `@login_required`

---

## File layout

```
tools/linedrawings/
├── CLAUDE.md           ← you are here
├── __init__.py         ← Blueprint definition only, imports routes at bottom
├── routes.py           ← All route handlers
├── services/
│   └── generate.py     ← Copied from ../../../Linedrawings/generate.py — do not modify
├── data/
│   └── linedrawings.db ← SQLite DB (generations + batch_runs tables)
├── templates/
│   └── linedrawings/   ← All templates live here
│       └── *.html      ← Each extends hub's "base.html"
└── static/
    └── linedrawings/   ← Tool-specific CSS/JS if needed
```

---

## Key rules

- **Never** touch `app.py`, `shared/`, `templates/base.html`, or other tools' folders
- **All** `url_for()` calls must use `linedrawings.` prefix (e.g. `url_for('linedrawings.gallery')`)
- **All** templates extend hub `"base.html"` — not the standalone LD base
- DB path is relative to this folder: `os.path.dirname(os.path.abspath(__file__))` → `data/linedrawings.db`
- Output dir: `tools/linedrawings/data/output/` (not project root)
- Uploads dir: `tools/linedrawings/data/uploads/`
- `generate.py` is imported as `from tools.linedrawings.services.generate import ...`
- No standalone auth — hub handles login

---

## Pages being ported (slimmed down)

| Source route | Hub route | Notes |
|---|---|---|
| `/` (dashboard) | `/linedrawings/` | Stats + recent gens + recent batches |
| `/products` | `/linedrawings/products` | Product list with LD status |
| `/generate` | `/linedrawings/generate` | Single SKU |
| `/batch` | `/linedrawings/batch` | Brand or XLSX batch |
| `/process` | `/linedrawings/process` | Live generation monitor |
| `/gallery` | `/linedrawings/gallery` | Review / approve / deny |
| `/missing` | `/linedrawings/missing` | Missing analysis |
| `/cross-check` | `/linedrawings/cross-check` | Model propagation helper |
| `/history` | `/linedrawings/history` | Batch history |

**Stripped**: `/login`, `/logout`, `/generate/status/<id>` (redirect to process instead), `/import-existing`

---

## Source app (read-only reference)
`C:\Users\Zach.Wright\Desktop\Projects\Linedrawings\app.py`  
`C:\Users\Zach.Wright\Desktop\Projects\Linedrawings\generate.py`

Do not modify these files.

---

## Build order
1. `services/generate.py` — copy + minor path fix
2. `routes.py` — all routes, auth swapped, url_for prefixed, paths fixed
3. `__init__.py` — blueprint + imports routes
4. Templates — one at a time, extending hub base.html
5. DB migration — copy existing linedrawings.db if it has data worth keeping
