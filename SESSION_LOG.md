# Roxor Content HUB — Session Log

---

## Session 1 — 2026-04-30

**Goal**: Project scoping, setup, and HUB shell build

### Decisions made

- Project lives in `C:\Users\Zach.Wright\Desktop\Projects\chairman mao\`
- Internal codename: **Chairman Mao**
- Public name: **Roxor Content HUB**
- Four tools to integrate:
  1. Line Drawing & Cutout Uploader — source: `../linedrawing pdf sorter thingy emily/` (working, deployed)
  2. Line Drawing Generator — source: `../Linedrawings/` (partially broken, being fixed in parallel)
  3. Lifestyle Brief Generator — source: `../lifestyle operations/website/` (built, needs port)
  4. Roxor Content Tracker — source: `../asset health monitor/` (Balterley-only → needs multi-brand upgrade)
- Approach: Flask Blueprints, one app, shared auth + branding
- Each tool fully self-contained in `tools/<name>/` — own routes, templates, static, services
- Build locally first, deploy when all tools are solid
- Multi-week project — source apps stay untouched

### Architecture built

- `app.py` — thin, registers blueprints, runs on port 5005
- `shared/auth.py` — single login, roles, per-tool access flags, migrates all users from briefs.db on first boot
- `shared/akeneo.py` + `shared/scaleflex.py` — shared API clients
- `blueprints/auth.py` — login/logout
- `blueprints/dashboard.py` — landing page + admin user management
- `tools/linedrawings/`, `tools/cutouts/`, `tools/briefs/`, `tools/content_tracker/` — placeholder blueprints
- `templates/base.html` — sidebar nav, topbar, user card
- `templates/dashboard.html` — 4 tool cards
- `templates/admin/users.html` + `new_user.html` — user management with per-tool access toggles
- `static/css/hub.css` — full Roxor dark navy/gold theme + light mode (white/gold/navy)

### Auth / permissions model

- Single login → access all tools you're granted
- Users table: username, password_hash, display_name, email, role (admin/user)
- Per-tool access: `access_linedrawings`, `access_cutouts`, `access_briefs`, `access_content_tracker`
- Admins bypass all access flags
- All users migrated from `lifestyle operations/website/data/briefs.db` on first boot
- New users created fresh via Admin → Manage Users

### UI

- Dark mode (default): navy `#02054F` / gold `#F2C400`
- Light mode: white bg / gold accents / navy text
- Toggle button (moon/sun) in sidebar footer, persists to localStorage
- Sidebar shows only the tools the logged-in user has access to

### Status at end of session

- HUB shell fully built and running at http://localhost:5005
- All 4 tool slots are placeholders (showing "coming soon")
- **Next: port the LD & Cutout Uploader (Emily tool) into `tools/cutouts/`**
- Zach hit weekly usage limit — continuing next session

---

## Session 2 — 2026-05-01

**Goal**: Port LD & Cutout Uploader + Lifestyle Brief Generator, JSZip for archive download, live DB migrations

### What was done

**LD & Cutout Uploader (`tools/cutouts/`)**
- Replaced server-side ZIP streaming with client-side JSZip (Cloudflare 439 fix)
- `download_archive` now returns JSON `{files:[{url,zip_path}]}` instead of streaming zip
- `index.html` updated with async JSZip downloader + progress overlay
- JSZip served locally from `static/js/jszip.min.js` (CDN blocked in this env)
- Migrated 1,519 records from live Emily server (3.11.244.252) into `tools/cutouts/data/cutouts.db`

**Lifestyle Brief Generator (`tools/briefs/`)**
- Full port from `../lifestyle operations/website/` — source app left untouched
- **Stripped**: analytics (lifestyle-tracker, cpi-tracker), MAAM briefs/invoices/deliveries, audit log, user management
- **Kept**: brief creation wizard, dashboard, downloads, designer uploads + review, model mappings (24,266), scenes (8)
- Services created: `services/akeneo.py`, `scaleflex.py`, `models.py`, `excel.py`, `notifications.py`
- Routes: 44 routes across dashboard, generate, processing, brief management, model mappings, scenes, uploads
- Templates: index, generate, processing, view_brief, model_mappings, scenes, uploads, uploads_review
- DB seeded from `lifestyle-briefs.duckdns.org`: 31 briefs, 24,266 model mappings, 1,241 excluded SKUs, 8 scenes, 2,433 uploads
- Hub auth: `admin` = full superadmin, `user+access_briefs` = can create/upload

### Status at end of session

- Cutouts tool: fully working with JSZip archive download ✓
- Briefs tool: fully ported — all 44 routes registered, app imports clean ✓
- **Next**: test briefs tool in browser, fix any template issues
- **Then**: content tracker port or linedrawings slot-in

---

## Session 3 — 2026-05-05

**Goal**: Content tracker — fix scanner, split asset/content scans, charts, gaps page, deploy script

### What was done

**Scanner rewrite (`services/scanner.py`)**
- Removed all CDN HEAD request code (`_check_image`, `_cdn_session`, ThreadPoolExecutor, requests imports)
- Assets now checked directly from Akeneo asset collection attributes (non-empty `data` array = linked)
- Split into `run_assets_scan` + `run_content_scan` — independent functions, independent threads
- Added `live_on_cs_cart` fetch during asset scan (stored as 0/1 in DB)
- Saves aggregate stats to `brand_stats` table after each scan (for trend charts)
- Trigger functions: `trigger_assets_scan`, `trigger_content_scan`, `trigger_scan` (both), plus scheduled variants

**Scheduler (`services/scheduler.py`)**
- Asset scans: 00:00, 00:10, … 01:30 (10 brands × 10 min apart)
- Content scans: 02:00, 02:10, … 03:30 (after assets finish)
- Job IDs: `assets_{brand}` and `content_{brand}` (was `nightly_{brand}`)

**Routes (`routes.py`)**
- DB init: new columns `assets_scanned`, `content_scanned`, `live_on_cs_cart` on `product_coverage`; `scan_type` on `scans`; new `brand_stats` table
- Live migrations via `PRAGMA table_info` so existing DBs upgrade safely
- Separate API endpoints: `POST /api/scan/assets`, `POST /api/scan/content` (keep `POST /api/scan` as combined)
- Scan status returns nested `{assets: {...}, content: {...}}` per brand
- Brand view passes chart data, CS Cart count, per-type gap counts
- New gaps view: `GET /brand/<brand>/gaps` → filterable table (content + asset tabs)
- CSV exports: `GET /api/export/<brand>/content`, `GET /api/export/<brand>/assets`
- Fixed `total_cols` bug in model view

**Templates**
- `index.html`: separate scan rows per brand (Assets + Content), with individual Scan buttons and progress
- `brand.html`: full rewrite — two tabs (Imagery / Content), Chart.js bar + donut charts, CS Cart toggle, worst models tables, scan progress bars, gaps link in topbar
- `gaps.html`: new — filterable table with filter dropdowns + search, CSV export buttons, asset + content gap tabs
- Chart.js 4.4.4 downloaded locally → `static/chart.min.js` (served via blueprint static)

**Deploy script added to CLAUDE.md**
- Pre-deploy: scp commands to freshen cutouts.db, briefs.db, and briefs uploads from live servers
- Full deploy script: rsync code → scp .env → scp DBs → rsync uploads → venv + pip → systemd service → nginx config
- Documented which DBs must NOT be overwritten after first launch

### Status at end of session

- Content tracker: scanner, routes, scheduler, all templates rebuilt ✓
- Deploy script: written, in CLAUDE.md ✓
- **Remaining**: linedrawings tool (routes + templates still placeholder)
- **Test**: run full scan once other editing sessions finish (Flask reload kills scan threads)
