# Content Briefs Tool — CLAUDE.md

Internal tool within the **Roxor Content HUB** (`chairman mao` project).  
URL prefix: `/content-briefs` · Blueprint: `content_briefs_bp`

**STATUS: BUILT & DEPLOYED — fully functional**

---

## What this tool does

Generates content briefs for copywriters. You supply a list of SKUs and configure:

1. **Scoped attributes** — per sales channel (e.g. `description` on `btbhub`). Brief tells the writer what scope(s) need copy written.
2. **Localised attributes** — per-locale values (e.g. `name` in `en_GB`, `de_DE`).
3. **Extra attributes** — global (non-scoped, non-localised): selling points, body copy, bullet points, etc.
4. **Reference attributes** — context-only columns pre-filled from Akeneo, highlighted teal in the spreadsheet. Not for writing — just for the writer's reference.

Output: a `.zip` containing an Excel brief with current Akeneo values pre-populated. Grey = has value, yellow = needs writing, teal = reference/context, pink = SKU not found in Akeneo.

---

## File layout

```
tools/content_briefs/
├── CLAUDE.md               ← you are here
├── __init__.py             ← Blueprint definition only
├── routes.py               ← All route handlers (14 routes)
├── services/
│   ├── __init__.py
│   ├── akeneo.py           ← AkeneoClient: product fetch, value extraction, metadata endpoints
│   └── excel.py            ← generate_content_brief() — 3-sheet Excel output
├── data/
│   └── content_briefs.db   ← SQLite DB (auto-created on first run)
├── briefs_output/          ← Generated Excel files stored here
├── templates/
│   └── content_briefs/
│       ├── index.html      ← Dashboard with stats + 3 sections (new/in-progress/complete)
│       ├── generate.html   ← Form: SKU list + Akeneo-powered attribute pickers
│       ├── processing.html ← Spinner → fires /api/process → redirect on done
│       └── view_brief.html ← Two-col: attr config + SKU list | meta panel + admin actions
└── static/
    └── content_briefs/     ← (empty — no tool-specific static needed yet)
```

---

## Routes (14 total)

| Method | URL | Function | Notes |
|--------|-----|----------|-------|
| GET | `/content-briefs/` | `index` | Dashboard |
| GET/POST | `/content-briefs/generate` | `generate` | Form + POST stores session, redirects to processing |
| GET | `/content-briefs/processing` | `processing` | Spinner page |
| POST | `/content-briefs/api/process` | `api_process` | Fetches Akeneo data, generates Excel, saves to DB |
| GET | `/content-briefs/view/<id>` | `view_brief` | Brief detail page |
| GET | `/content-briefs/download/<id>` | `download` | Streams ZIP; auto-sets status to in_progress on first download |
| POST | `/content-briefs/delete/<id>` | `delete_brief` | Admin only; deletes DB record + output folder |
| POST | `/content-briefs/update-status/<id>` | `update_status` | Admin: status dropdown |
| POST | `/content-briefs/update-priority/<id>` | `update_priority` | Admin only |
| POST | `/content-briefs/assign/<id>` | `assign_brief` | Admin only; sets assigned_to + flips status to assigned/pending |
| POST | `/content-briefs/api/briefs/<id>/deadline` | `update_deadline` | Admin; JSON POST `{deadline}` |
| GET | `/content-briefs/api/attributes` | `api_attributes` | Returns {attributes, channels, locales} from Akeneo; 1hr cache |
| POST | `/content-briefs/api/attributes/refresh` | `api_attributes_refresh` | Busts the attribute cache |

---

## DB schema (content_briefs.db)

```sql
CREATE TABLE IF NOT EXISTS content_briefs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    name            TEXT NOT NULL,
    sku_count       INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'pending',     -- pending / assigned / in_progress / complete
    priority        TEXT DEFAULT 'normal',      -- low / normal / high / urgent
    assigned_to     INTEGER,                    -- hub user id (from hub.db)
    deadline        TEXT,
    output_path     TEXT,                       -- path to briefs_output/{name}_{timestamp}/
    downloaded_at   TEXT,
    downloaded_by   INTEGER,
    completed_at    TEXT,
    scoped_attrs    TEXT DEFAULT '{}',          -- {"scope_code": ["attr1", ...], ...}
    locale_attrs    TEXT DEFAULT '{}',          -- {"locale_code": ["attr1", ...], ...}
    extra_attrs     TEXT DEFAULT '[]',          -- ["attr1", "attr2", ...]
    reference_attrs TEXT DEFAULT '[]',          -- ["attr1", "attr2", ...]
    notes           TEXT,
    sku_list        TEXT,                       -- JSON array of SKUs
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Migration pattern is in `init_db()` — uses `PRAGMA table_info` check before `ALTER TABLE`.

---

## Key rules

- **Never** touch `app.py`, `shared/`, `templates/base.html`, or other tools' folders
- **All** routes decorated `@tool_access_required('content_briefs')` — never `@login_required`
- **All** `url_for()` calls prefixed `content_briefs.`
- **All** templates extend hub `"base.html"`
- No CSRF — hub doesn't use Flask-WTF
- Hub users come from `hub.db` via `HUB_DB_PATH` imported from `shared.auth`

---

## Akeneo integration

### AkeneoClient (`services/akeneo.py`)

- `get_product(sku)` — single product fetch
- `get_products(skus)` — batch fetch (sequential)
- `get_product_values(product, sku, scoped_attrs, locale_attrs, extra_attrs, reference_attrs=None)` — returns structured dict:
  ```python
  {
    'sku': '...',
    'found': True/False,
    'values': {
      'scoped':    {'scope_code': {'attr': 'value'}},
      'locale':    {'locale_code': {'attr': 'value'}},
      'extra':     {'attr': 'value'},
      'reference': {'attr': 'value'},
    }
  }
  ```
- `get_all_attributes()` — paginated; returns `[{code, label, type, scopable, localizable}]`
- `get_channels()` — returns `[{code, label}]`
- `get_active_locales()` — returns `[{code}]`

### Attribute value extraction

Akeneo values are lists of `{scope, locale, data}` dicts. `_get_value()` tries:
1. Exact scope+locale match
2. Scope-only match
3. Locale-only match
4. First entry fallback

### Attribute cache

`_attr_cache` module-level dict, 1-hour TTL. `api_attributes` route serves cached data.  
Bust with POST to `api_attributes/refresh`.

---

## Generate form (generate.html)

JS-driven attribute picker — no manual text input.

- On page load: fires `loadData()` → `GET /api/attributes` → populates dropdowns
- **Scoped block**: select channel from dropdown → "+ Add Channel" → creates block with searchable attr dropdown (scopable attrs only)
- **Locale block**: select locale → "+ Add Locale" → block with searchable attr dropdown (localizable attrs only)
- **Extra**: searchable dropdown for global attrs (not scopable, not localizable)
- **Reference**: searchable dropdown for any attr (all attrs in pool)
- On submit: `serializeState()` serialises state to hidden JSON fields → POST

Hidden fields posted: `scoped_attrs_json`, `locale_attrs_json`, `extra_attrs_json`, `reference_attrs_json`

---

## Excel output (services/excel.py)

`generate_content_brief(rows, output_path, scoped_attrs, locale_attrs, extra_attrs, brief_name='', notes=None, reference_attrs=None)`

**Sheet 1 — Content Brief**: one row per SKU, colour-coded columns:
- Navy header → SKU / Found metadata
- Blue header → Scoped attributes `[scope]\nattr`
- Green header → Localised attributes `[locale]\nattr`
- Amber header → Extra (global) attributes
- Teal header → Reference columns `REF\nattr`
- Grey cell → has existing Akeneo value
- Yellow cell → empty, needs writing
- Teal cell → reference column (always grey regardless of value)
- Pink/red cell → SKU not found in Akeneo

**Sheet 2 — Brief Config**: metadata (name, date, SKU count, notes, attr breakdown)  
**Sheet 3 — Key**: colour legend

---

## Assignment

`assign_brief` route:
- Admin only
- `GET /content-briefs/assign/<id>` POST with `assigned_to` (user id or empty)
- Sets `assigned_to` + flips status: `assigned` if user set, `pending` if cleared
- `get_hub_users()` queries hub.db for `access_content_briefs = 1 AND status = 'active'`

---

## Gotchas

- Akeneo values are **lists** — never assume index 0. Always filter by scope/locale explicitly.
- Some attrs are both scopable AND localizable. `_get_value()` handles all three cases.
- `__init__.py` must import routes **after** defining the blueprint — circular import otherwise.
- Hub doesn't use Flask-WTF — no `{{ csrf_token() }}` in forms, no `X-CSRFToken` in JS fetch.
- `access_content_briefs` is in `shared/auth.py` create table + migration + seed, `templates/admin/users.html`, `templates/admin/new_user.html`, `blueprints/dashboard.py`, and `templates/base.html` sidebar.
- `briefs_output/` folder is created by `os.makedirs` at module load — will exist on first run.
