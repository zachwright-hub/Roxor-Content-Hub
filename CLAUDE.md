# Roxor Content HUB — CLAUDE.md

## What this project is

A unified internal web app ("Roxor Content HUB") that consolidates four content tools into one Flask app with shared auth, shared Roxor branding, and a central dashboard. Known internally as "Chairman Mao" during development.

**Local URL**: http://localhost:5005 (when running)
**Run**: `python app.py` from this folder

---

## Project structure

```
chairman mao/
├── app.py                      # Thin — registers blueprints, runs app, nothing else
├── CLAUDE.md
├── SESSION_LOG.md
├── requirements.txt
├── .env
├── data/
│   └── hub.db                  # Shared users/sessions DB
├── shared/
│   ├── auth.py                 # tool_access_required('tool_name') decorator
│   ├── akeneo.py               # Shared Akeneo API client
│   └── scaleflex.py            # Shared Scaleflex API client
├── templates/
│   ├── base.html               # Shared nav/layout shell
│   ├── dashboard.html          # Hub landing page
│   └── auth/
│       └── login.html
├── static/
│   ├── css/hub.css             # Shared Roxor branding only
│   └── js/
│       └── jszip.min.js        # Served locally (CDN blocked by Cloudflare 439)
└── tools/
    ├── linedrawings/           # LINE DRAWING GENERATOR (IN PROGRESS — services/generate.py done)
    │   ├── CLAUDE.md           # Tool-specific docs
    │   ├── __init__.py         # Placeholder only — routes.py not yet written
    │   ├── services/
    │   │   └── generate.py     # Ported from ../Linedrawings/generate.py ✓
    │   ├── data/               # linedrawings.db goes here (not yet copied)
    │   ├── templates/linedrawings/
    │   └── static/linedrawings/
    ├── cutouts/                # CUTOUT SORTER ✓ DONE
    │   ├── __init__.py
    │   ├── routes.py
    │   ├── data/cutouts.db     # 1519 records migrated from live Emily server
    │   ├── templates/cutouts/
    │   └── static/cutouts/
    ├── briefs/                 # LIFESTYLE BRIEF GENERATOR ✓ DONE
    │   ├── __init__.py
    │   ├── routes.py           # 44 routes
    │   ├── data/briefs.db      # Live DB: 12 users, 31 briefs, 24266 model_mappings, 2433 uploads
    │   ├── services/
    │   ├── templates/briefs/
    │   └── static/briefs/
    └── content_tracker/        # ROXOR CONTENT TRACKER ✓ DONE
        ├── __init__.py
        ├── routes.py
        ├── data/tracker.db     # product_coverage + scans tables
        ├── services/
        │   └── akeneo.py       # Copied from asset health monitor
        ├── templates/content_tracker/
        │   ├── index.html      # Brand grid dashboard
        │   ├── brand.html      # Model list with coverage pip bars
        │   └── model.html      # SKU-level ✓/✗ per asset family
        └── static/content_tracker/
```

### Key principle: tools are self-contained

- **Everything a tool needs lives inside its own folder** — routes, templates, static files, services
- Auth: `@tool_access_required('tool_name')` from `shared/auth.py` — use in every route
- `app.py` does nothing except register blueprints and run the server

---

## Source apps (do not modify these originals)

| Tool | Source folder | Status |
|------|--------------|--------|
| Line Drawing Generator | `../Linedrawings/` | IN PROGRESS — services/generate.py done, routes.py + templates next |
| Cutout Sorter | `../linedrawing pdf sorter thingy emily/` | PORTED ✓ |
| Lifestyle Brief Generator | `../lifestyle operations/website/` | PORTED ✓ (stripped) |
| Roxor Content Tracker | `../asset health monitor/` | REBUILT multi-brand ✓ |

**Never modify the source folders.**

---

## Branding

- **Dark navy**: `#02054F` / Background: `#0a0f2e`
- **Gold**: `#F2C400`
- **Font**: Inter (sans-serif)
- CSS vars: `var(--gold)`, `var(--navy)`, `var(--surface)`, `var(--surface-2)`, `var(--border)`, `var(--text)`, `var(--text-muted)`
- Hub has no `--success` or `--danger` — use `#4caf50` and `#e53935` directly

---

## Auth

- Single login → access all tools
- Sessions in `data/hub.db`
- Decorator: `@tool_access_required('tool_name')` — checks session + per-tool access flag
- Cookie: `SESSION_COOKIE_HTTPONLY=True`, `SAMESITE=Lax`

---

## Environment variables (`.env`)

```
SESSION_SECRET=
AKENEO_URL=
AKENEO_CLIENT_ID=
AKENEO_CLIENT_SECRET=
AKENEO_USERNAME=
AKENEO_PASSWORD=
SCALEFLEX_WORKSPACE=xa38qjmpah
SCALEFLEX_API_KEY=
```

---

## URL routing

| Tool | URL prefix |
|------|-----------|
| Line Drawing Generator | `/linedrawings` |
| Cutout Sorter | `/cutouts` |
| Lifestyle Brief Generator | `/briefs` |
| Roxor Content Tracker | `/content-tracker` |

---

## Cutouts tool — key details

- **DB**: `tools/cutouts/data/cutouts.db` — 1519 records (1396 approved, 123 denied) migrated from Emily server at `3.11.244.252`
- **JSZip client-side download** — server returns JSON list of `{url, zip_path}`, browser downloads from CDN and zips locally using `static/js/jszip.min.js`
- **Why client-side**: `files.roxorgroup.com` Cloudflare blocks server/datacenter IPs (439 error) but allows browser requests
- **Archive route** (`/api/download-archive`): returns JSON, excludes `ZIP_EXCLUDED_BRANDS`
- **`static/js/jszip.min.js`**: served locally — CDN version blocked by same Cloudflare issue

---

## Briefs tool — key details

- Ported from `../lifestyle operations/website/` — stripped to core features only
- **Kept**: dashboard, brief creation/processing, downloads, assign/status/priority, uploads portal, uploads review, model mappings, scenes, send-back-brief, scan-completions
- **Stripped**: login/auth (hub handles it), admin user management, audit log, lifestyle tracker/analytics, CPI tracker, MAAM
- **DB**: pulled live from `ubuntu@3.11.47.120:/var/www/brief-generator/website/data/briefs.db`
- **44 routes** — all prefixed `/briefs/...`, all decorated `@tool_access_required('briefs')`
- **No CSRF** — hub doesn't use Flask-WTF; all CSRF token headers removed from JS
- **Uploads review** (`templates/briefs/uploads_review.html`):
  - Table view with preview thumbnail + cutout thumbnail per row
  - Full slideshow modal: side-by-side cutout ref + upload, SKU input, type select, Approve/Reject
  - Reject panel with feedback textarea + Send Back
  - Keyboard nav: ArrowLeft/Right, Escape to close
  - Auto-advances 800ms after approve/reject
  - "Review Slideshow (N)" button in topbar — pending tab only
- **Preview URLs**: `/briefs/api/uploads/{id}/preview`, `/briefs/api/cutout/{sku}`

---

## Content Tracker tool — key details

- **Multi-brand**, not ported from asset health monitor — fresh build
- **10 brands**: balterley, nuie, bc_designs, hudson_reed, bc_sanitan, bayswater, wickes, arley, arley_pro, synergy
- **Scan approach**: two-phase
  1. Server fetches SKU list from Akeneo (brand IN filter, `parent` field → parent_model)
  2. Browser checks CDN URLs directly using `new Image()` — same pattern as JSZip fix, bypasses Cloudflare 439
- **CDN**: `https://files.roxorgroup.com/{SKU}{suffix}.jpg` (falls back to `.png` for `_ld`)
- **Asset families checked** (suffix → family name):
  ```
  _co1 → cutout_1      _co2 → cutout_2
  _ld  → line_drawing
  _ls1 → lifestyle_1   _ls2 → lifestyle_2   _ls3 → lifestyle_3
  _pc  → premium_cutout
  _pa1–_pa8 → premium_asset_1–8
  ```
- **DB tables**: `product_coverage` (sku, brand, parent_model, akeneo_family, assets JSON, content JSON, last_scanned) + `scans`
- **Views**: index (brand grid) → brand (model list) → model (SKU ✓/✗ per family)
- **Only shows active families** — families with any data for that brand/model, not all 15 every time
- **Batch size**: 30 parallel image checks at a time
- **`__init__.py` gotcha**: must import routes AFTER defining the blueprint (circular import if done inline). Clear pycache if you see `ImportError: cannot import name 'routes'`

---

## Line Drawing Generator — next steps

- `tools/linedrawings/routes.py` — port all routes from `../Linedrawings/app.py`, swap auth decorator, fix paths
- `tools/linedrawings/__init__.py` — update to import routes (currently placeholder only)
- Templates — one by one extending hub `base.html`
- Copy `../Linedrawings/linedrawings.db` → `tools/linedrawings/data/linedrawings.db`
- **Prompts**: per-category prompt system to be built after deployment review
  - Sample designer drawings in `../Linedrawings/samples/` show target quality
  - Shower tray: top-down plan view. Concealed valve: two views (front + side section). Wall tap: two views.
  - Current single-photo → AI approach can approximate the view/angle but not full engineering detail
  - Agreed: build `CATEGORY_PROMPTS` dict mapping product groups → specific view + dimension placement rules

---

## Deployment

- Target: single AWS Lightsail instance (TBD — Zach to confirm server)
- nginx reverse proxy → Flask/Gunicorn on port 5005
- systemd service: `roxor-content-hub.service`
- Path: `/var/www/roxor-content-hub/`
- Gunicorn: `--workers 1` (APScheduler runs in-process — single worker avoids duplicate scheduler)
- **Note**: actual folder layout uses `UI/templates` and `UI/static`

---

### Pre-deploy: freshen data from live servers

Run these locally (from the project folder) right before deploying to get the most current data:

```bash
# 1. Fresh briefs DB (from live briefs server)
scp -i "C:/Users/Zach.Wright/Desktop/Projects/lifestyle operations/website/LightsailDefaultKey.pem" \
    ubuntu@3.11.47.120:/var/www/brief-generator/website/data/briefs.db \
    tools/briefs/data/briefs.db

# 2. Briefs uploads folder (designers' images — can be large, use rsync to only grab new)
rsync -avz -e "ssh -i 'C:/Users/Zach.Wright/Desktop/Projects/lifestyle operations/website/LightsailDefaultKey.pem'" \
    ubuntu@3.11.47.120:/var/www/brief-generator/website/uploads/ \
    tools/briefs/uploads/

# 3. Fresh cutouts DB (from Emily/LD sorter server)
scp -i "C:/Users/Zach.Wright/Desktop/Projects/gemini lifestyles/LightsailDefaultKey-eu-west-2 (1).pem" \
    ubuntu@3.11.244.252:/var/www/ld-pdf-sorter/data/cutouts.db \
    tools/cutouts/data/cutouts.db
```

> Note: Check the SSH key paths — they may differ. The briefs server key might be the same as the LD sorter key. Ask Zach if unsure.

---

### Deploy to server

```bash
# ── On local machine: copy files to server ──────────────────────────────────
SERVER=ubuntu@<IP>   # Zach to confirm IP
KEY="<path-to-pem>"

# Sync code (exclude DBs and uploads — they're handled separately)
rsync -avz --exclude='*.db' --exclude='*.db-journal' \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.env' \
    --exclude='tools/briefs/uploads/' \
    -e "ssh -i '$KEY'" \
    "C:/Users/Zach.Wright/Desktop/Projects/chairman mao/" \
    "$SERVER:/var/www/roxor-content-hub/"

# Copy .env (update SESSION_SECRET for prod first)
scp -i "$KEY" "C:/Users/Zach.Wright/Desktop/Projects/chairman mao/.env" \
    "$SERVER:/var/www/roxor-content-hub/.env"

# Copy freshened DBs
scp -i "$KEY" tools/briefs/data/briefs.db         "$SERVER:/var/www/roxor-content-hub/tools/briefs/data/briefs.db"
scp -i "$KEY" tools/cutouts/data/cutouts.db       "$SERVER:/var/www/roxor-content-hub/tools/cutouts/data/cutouts.db"
scp -i "$KEY" data/hub.db                          "$SERVER:/var/www/roxor-content-hub/data/hub.db"

# Sync uploads (briefs)
rsync -avz -e "ssh -i '$KEY'" \
    tools/briefs/uploads/ \
    "$SERVER:/var/www/roxor-content-hub/tools/briefs/uploads/"


# ── On server ───────────────────────────────────────────────────────────────
ssh -i "$KEY" $SERVER

sudo mkdir -p /var/www/roxor-content-hub
sudo chown ubuntu:ubuntu /var/www/roxor-content-hub
cd /var/www/roxor-content-hub

# First deploy only: create venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Subsequent deploys: just update deps if requirements changed
source venv/bin/activate
pip install -r requirements.txt --quiet

# Create systemd service (first deploy only)
sudo tee /etc/systemd/system/roxor-content-hub.service > /dev/null <<'EOF'
[Unit]
Description=Roxor Content HUB
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/var/www/roxor-content-hub
EnvironmentFile=/var/www/roxor-content-hub/.env
ExecStart=/var/www/roxor-content-hub/venv/bin/gunicorn --workers 1 --bind 127.0.0.1:5005 --timeout 120 app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable roxor-content-hub

# nginx config (first deploy only) — save as /etc/nginx/sites-available/roxor-content-hub
sudo tee /etc/nginx/sites-available/roxor-content-hub > /dev/null <<'EOF'
server {
    listen 80;
    server_name _;

    location /static/ {
        alias /var/www/roxor-content-hub/UI/static/;
        expires 7d;
    }

    location / {
        proxy_pass http://127.0.0.1:5005;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 120;
    }
}
EOF
sudo ln -sf /etc/nginx/sites-available/roxor-content-hub /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# Start / restart service
sudo systemctl start roxor-content-hub   # first deploy
sudo systemctl restart roxor-content-hub # subsequent deploys

# Check logs
journalctl -u roxor-content-hub -f
```

---

### DO NOT overwrite on redeploy

- `data/hub.db` — hub users/sessions (live data after launch)
- `tools/content_tracker/data/tracker.db` — scan history (grows with every nightly scan)
- `tools/briefs/data/briefs.db` — live briefs (hub becomes source of truth after launch)
- `tools/cutouts/data/cutouts.db` — live cutout records

After first launch: old servers (`3.11.47.120` briefs, `3.11.244.252` Emily) become read-only backups. The hub is source of truth.
