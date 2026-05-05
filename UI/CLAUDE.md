# Roxor Content HUB — UI Layer

## What this folder owns

This folder contains the **shared** UI for the Chairman Mao hub — the shell that wraps every tool. It does NOT contain per-tool UI (those live inside `tools/*/templates/` and `tools/*/static/`).

```
UI/
├── templates/
│   ├── base.html           # Shared nav/layout shell — every page extends this
│   ├── dashboard.html      # Hub landing page
│   ├── coming_soon.html    # Placeholder for tools not yet live
│   ├── auth/
│   │   └── login.html      # Login page
│   └── admin/
│       ├── users.html      # User list + access control
│       └── new_user.html   # Create user form
└── static/
    ├── css/
    │   └── hub.css         # Shared Roxor branding — CSS vars, nav, global styles
    └── js/
        └── jszip.min.js    # Served locally (CDN blocked by Cloudflare 439)
```

`app.py` points Flask here via:
```python
Flask(__name__, template_folder='UI/templates', static_folder='UI/static')
```

---

## Branding

- **Dark navy**: `#02054F` / Background: `#0a0f2e`
- **Gold**: `#F2C400`
- **Font**: Inter (sans-serif)
- CSS vars: `var(--gold)`, `var(--navy)`, `var(--surface)`, `var(--surface-2)`, `var(--border)`, `var(--text)`, `var(--text-muted)`
- No `--success` / `--danger` vars — use `#4caf50` and `#e53935` directly

---

## base.html — key points

- Every tool template does `{% extends 'base.html' %}`
- Provides: top nav with hub logo + tool links, `{% block content %}`, flash messages
- Nav links are active-highlighted based on `request.blueprint`
- `current_user` is injected globally via `app.context_processor` in `app.py`

---

## Scope for this terminal

This terminal owns:
- `UI/templates/` — all shared templates above
- `UI/static/css/hub.css` — shared CSS only
- `UI/static/js/` — shared JS assets

**Do not touch** tool-specific templates (`tools/*/templates/`) or tool-specific static (`tools/*/static/`) — those belong to their respective tool terminals.

---

## Running locally

```
cd "C:\Users\Zach.Wright\Desktop\Projects\chairman mao"
python app.py
```

URL: http://localhost:5005
