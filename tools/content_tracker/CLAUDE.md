# Content Tracker — CLAUDE.md

Internal tool within the **Roxor Content HUB** (`chairman mao` project).
URL prefix: `/content-tracker` · Blueprint: `content_tracker_bp`

---

## Current state (as of 2026-05-05)

### What's built

| File | Status |
|------|--------|
| `state.py` | ✓ Shared `_scan_state` dict + lock |
| `routes.py` | ✓ Rewritten — brand/model views, config, API endpoints |
| `services/akeneo.py` | ✓ Working Akeneo client — do not modify |
| `services/scanner.py` | ✓ Built — BUT image approach needs changing (see below) |
| `services/scheduler.py` | ✓ APScheduler midnight cron, 10 brands staggered |
| `templates/index.html` | ✓ Brand grid, scan buttons, poll-based progress |
| `templates/brand.html` | ✓ Model list, asset pip bars, content % column |
| `templates/model.html` | ✓ Image tab + content tab |
| `templates/config.html` | ✓ Per-brand JSON editor |
| `data/tracker.db` | Empty — no successful scan yet |

### What still needs building (next session picks up here)

1. **Fix image scan approach** — see section below, currently wrong
2. **Split asset scan and content scan** — two separate jobs/triggers per brand
3. **Charts and in-depth stats** — see requirements below, awaiting Zach input on specifics
4. **Missing attributes export** — CSV download per brand of SKUs failing content checks
5. **Test end to end** — wait until all other editing sessions are done before running scans (Flask reloads kill scan threads mid-run)

---

## Image checking — CONFIRMED CORRECT APPROACH

**Check Akeneo asset collection attributes directly. Not CDN. Not Scaleflex.**

Cloudflare 439s ALL server-side requests to `files.roxorgroup.com` — HEAD, GET, everything.
The website/channels read from Akeneo to know which images to display, so Akeneo is the source of truth anyway.

For each product, check if these Akeneo attribute values have a non-empty data array:

```python
ASSET_FAMILIES = [
    'cutout_1', 'cutout_2', 'line_drawing',
    'lifestyle_1', 'lifestyle_2', 'lifestyle_3',
    'premium_cutout',
    'premium_asset_1', ..., 'premium_asset_8',
]
```

Akeneo asset collection values look like:
```json
"cutout_1": [{"locale": null, "scope": null, "data": ["BABT302_co1"]}]
```
If `data` array is non-empty → asset is linked → `True`. Empty or missing → `False`.

**Remove all CDN HEAD request code from `scanner.py`** — `_check_image`, `_cdn_session`, CDN imports, ThreadPoolExecutor. Replace with simple attribute check against the product values already fetched from Akeneo.

This makes the scan MUCH faster — no extra HTTP calls at all, asset data comes from the same Akeneo product fetch used for content checking.

---

## Split scan architecture — CONFIRMED

Two separate scan types per brand, triggered and scheduled independently:

### Asset scan
- Checks: `cutout_1`, `cutout_2`, `line_drawing`, `lifestyle_1–3`, `premium_cutout`, `premium_asset_1–8`
- Source: Akeneo product values (asset collection attributes)
- Schedule: nightly, staggered from **00:00**
- Trigger: `POST /api/scan/assets` `{"brand": "balterley"}`
- Stores result in `product_coverage.assets` column

### Content scan
- Checks: configured required attributes per scope per brand (title, description, features, bullet_points etc.)
- Source: Akeneo product values (text/scopable attributes)
- Schedule: nightly, staggered from **02:00** (after asset scans finish)
- Trigger: `POST /api/scan/content` `{"brand": "balterley"}`
- Stores result in `product_coverage.content` column

Both scans fetch from Akeneo independently. They can run simultaneously for different brands. Both update `_scan_state[brand]['assets']` and `_scan_state[brand]['content']` separately so the UI can show progress for each independently.

### DB change needed
Add `assets_scanned` and `content_scanned` separate timestamps to `product_coverage`:
```sql
ALTER TABLE product_coverage ADD COLUMN assets_scanned TEXT;
ALTER TABLE product_coverage ADD COLUMN content_scanned TEXT;
```
And add `scan_type TEXT` column to `scans` table (values: `'assets'` or `'content'`).

### Scheduler change
```python
# Asset scans: brands 0–9 from 00:00, 10 min apart
# Content scans: brands 0–9 from 02:00, 10 min apart
# So balterley: assets 00:00, content 02:00
#    nuie:      assets 00:10, content 02:10
#    ...etc
```

---

## Page structure — CONFIRMED

Brand view (`/content-tracker/brand/<brand>`) has **two completely separate tabs**:

### Tab 1: Imagery
- Shows asset family coverage (cutout_1, line_drawing, lifestyle_1 etc.) per model/SKU
- **CS Cart filter toggle**: "All products" vs "CS Cart active only"
  - `live_on_cs_cart` boolean Akeneo attribute — must be fetched during asset scan and stored in DB
  - When toggled, stats + table filter to only show SKUs where `live_on_cs_cart = True`
- Charts (see below)
- "View Gaps" button → asset gaps report

### Tab 2: Content
- Shows text attribute coverage (title, description, features/bullets) per scope per model/SKU
- Charts (see below)
- "View Gaps" button → content gaps report

---

## Charts and stats — CONFIRMED

Both tabs (Imagery and Content) get charts. Chart.js — serve locally, no CDN.

### Imagery charts
- **Bar chart**: % of SKUs with each asset family (cutout_1, line_drawing, lifestyle_1 etc.) — shows which families are weakest
- **Donut/summary**: overall % of SKUs fully imaged (have cutout_1 at minimum) vs partial vs none
- **Trend line**: coverage % over time (needs scan history — each completed scan stored with aggregate stats)
- **Worst models table**: top 10 models with lowest asset coverage %

### Content charts
- **Bar chart**: % complete per scope (ecommerce, shopify, Tesco etc.)
- **Stacked bar**: per scope, how many SKUs have title ✓ / description ✓ / features ✓ etc.
- **Trend line**: overall content % over time
- **Worst models table**: top 10 models with lowest content coverage %

### DB change needed for trends
Add `brand_stats` table to store aggregate snapshot per completed scan:
```sql
CREATE TABLE IF NOT EXISTS brand_stats (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    brand          TEXT NOT NULL,
    scan_type      TEXT NOT NULL,  -- 'assets' or 'content'
    recorded_at    TEXT NOT NULL,
    total_skus     INTEGER,
    stats_json     TEXT            -- JSON blob: {family/scope: pct, ...}
);
```
Populated at the end of each scan, used to draw trend lines.

---

## CS Cart filter — CONFIRMED

`live_on_cs_cart` is a global boolean Akeneo attribute (scope=null, locale=null).

### DB change needed
```sql
ALTER TABLE product_coverage ADD COLUMN live_on_cs_cart INTEGER DEFAULT 0;  -- 0/1 boolean
```

### Fetch during asset scan
```python
cs_cart_vals = product.get('values', {}).get('live_on_cs_cart', [])
live_on_cs_cart = bool(cs_cart_vals[0].get('data')) if cs_cart_vals else False
```

### UI behaviour
- Toggle button in Imagery tab: "All" / "CS Cart" 
- When "CS Cart" selected: filter model list and all stats to only include SKUs where live_on_cs_cart=1
- Gap count badge updates to reflect filter
- Charts recompute for filtered set

---

## Missing attributes export — CONFIRMED

Gaps report — only shows rows where an attribute is MISSING. Filterable table in the UI with a CSV download button.

### Format: one row per missing attribute
```
sku, parent_model, category (akeneo_family), scope, attribute
BABT302, BABT30, accessories, ecommerce, title
BABT302, BABT30, accessories, Tesco, bullet_point_3
```

Only missing attributes appear — if everything is filled, the export is empty.

### UI page: `/content-tracker/brand/<brand>/gaps`
- Table with columns: SKU | Model | Category | Scope | Attribute
- Filter dropdowns: Category (akeneo_family), Scope, Attribute
- "Export CSV" button downloads the current filtered view
- Row count shown: "X gaps across Y SKUs"
- Link from brand view topbar: "View Gaps (N)" showing total gap count

### CSV endpoint
`GET /content-tracker/api/export/<brand>` — returns CSV of all missing attrs for that brand
`GET /content-tracker/api/export/<brand>?category=accessories&scope=ecommerce` — filtered

### Asset gaps
Same page, toggle between Content Gaps and Asset Gaps tabs.
Asset gaps format:
```
sku, parent_model, category, asset_family
BABT302, BABT30, accessories, line_drawing
BABT302, BABT30, accessories, lifestyle_1
```

---

## Per-brand content config — FULLY CONFIRMED

### Attribute codes (verified against live Akeneo)
- `title` — scopable, locale `en_GB`
- `description` — scopable, locale `null`
- `Selling_Copy` — scopable, locale `null` (b_and_q only)
- `features` — scopable, locale `en_GB` (single text field with dash-separated list, NOT bullet_point_N)
- `bullet_point_1` through `bullet_point_8` — scopable, locale `en_GB`

### Balterley

| scope | title | description | Selling_Copy | bullet_point_1–8 |
|-------|-------|-------------|--------------|------------------|
| `ecommerce` | ✓ | ✓ | — | — |
| `shopify` | ✓ | ✓ | — | — |
| `ebay` | ✓ | ✓ | — | — |
| `amazon_seller` | ✓ | ✓ | — | ✓ |
| `Tesco` | ✓ | ✓ | — | ✓ |
| `Debenhams` | ✓ | ✓ | — | ✓ |
| `b_and_q` | ✓ | ✓ | ✓ | ✓ |

### All other brands (nuie, bc_designs, hudson_reed, bc_sanitan, bayswater, wickes, arley, arley_pro, synergy)
```json
{"ecommerce": ["title", "description", "features"]}
```

---

## DB schema (actual current state)

```sql
CREATE TABLE product_coverage (
    sku           TEXT PRIMARY KEY,
    brand         TEXT NOT NULL,
    parent_model  TEXT,
    akeneo_family TEXT,
    assets        TEXT DEFAULT '{}',   -- {family_name: bool} from Akeneo asset attrs
    content       TEXT DEFAULT '{}',   -- {scope: {attr: bool}}
    last_scanned  TEXT
    -- TODO: add assets_scanned TEXT, content_scanned TEXT
);

CREATE TABLE scans (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    brand         TEXT NOT NULL,
    status        TEXT DEFAULT 'running',
    triggered_by  TEXT DEFAULT 'manual',
    product_count INTEGER DEFAULT 0,
    started_at    TEXT,
    completed_at  TEXT,
    error         TEXT
    -- TODO: add scan_type TEXT ('assets' or 'content')
);

CREATE TABLE brand_config (
    brand          TEXT PRIMARY KEY,
    required_attrs TEXT DEFAULT '{}',
    updated_at     TEXT
);
```

---

## Brands

```python
BRANDS = [
    ('balterley',   'Balterley'),
    ('nuie',        'Nuie'),
    ('bc_designs',  'BC Designs'),
    ('hudson_reed', 'Hudson Reed'),
    ('bc_sanitan',  'BC Sanitan'),
    ('bayswater',   'Bayswater'),
    ('wickes',      'Wickes'),
    ('arley',       'Arley'),
    ('arley_pro',   'Arley Pro'),
    ('synergy',     'Synergy'),
]
```

---

## Shared infrastructure

- **Auth**: `from shared.auth import tool_access_required` → `@tool_access_required('content_tracker')`
- **Akeneo client**: `tools/content_tracker/services/akeneo.py` — `get_all_products_streaming(search=...)` yields pages of product dicts with full `values`. Do not modify.
- **Scaleflex**: do NOT use for anything in this tool
- **Hub DB**: `data/hub.db` — users/sessions only
- **Tracker DB**: `tools/content_tracker/data/tracker.db`
- **Scan state**: `tools/content_tracker/state.py` — `_scan_state` dict, `_scan_lock`

---

## Gotchas

- Cloudflare 439s ALL server requests to `files.roxorgroup.com` — HEAD, GET, everything. Do not attempt CDN checks.
- `__init__.py` must import routes AFTER defining the blueprint.
- Flask debug mode + Werkzeug reloader: APScheduler must only start when `WERKZEUG_RUN_MAIN == 'true'`. Already wired in `app.py`.
- Flask reloads kill background scan threads — do not test scans while other sessions are actively editing files.
- SQLite `ALTER TABLE ADD COLUMN` has no `IF NOT EXISTS` — check with `PRAGMA table_info` first.
- `content_tracker_bp` registered at `/content-tracker` — URLs use hyphen not underscore.
- Akeneo `get_all_products_streaming` uses `search_after` pagination — yields pages, each page is a list.
- `_scan_state[brand]` is a dict mutated in place — always use `.update()` not reassignment.
- `content` scope checking: `v.get('scope') == scope` — note Tesco, Debenhams, b_and_q are capitalised in Akeneo exactly as shown.

---

## Deployment

- **Server**: TBC — Zach to confirm which Lightsail instance or new one
- **Port**: 5005 (Flask internal), nginx reverse proxy on 80/443
- **Service**: `roxor-content-hub.service` (systemd)
- **Path**: `/var/www/roxor-content-hub/`
- **Python**: virtualenv at `/var/www/roxor-content-hub/venv/`
- **Gunicorn**: `gunicorn --workers 2 --bind 127.0.0.1:5005 app:app`
  - NOTE: APScheduler runs in-process — use `--workers 1` or `--preload` to avoid multiple scheduler instances
- **nginx config**: standard reverse proxy to 127.0.0.1:5005
- **.env**: copy from local, update SESSION_SECRET for production
- **DB**: `data/hub.db` and `tools/content_tracker/data/tracker.db` — do NOT overwrite on redeploy
- **Static files**: served by nginx for `/static/` prefix for performance
- **Logs**: `journalctl -u roxor-content-hub -f`

### Deploy steps
```bash
# On server
sudo mkdir -p /var/www/roxor-content-hub
sudo chown ubuntu:ubuntu /var/www/roxor-content-hub
cd /var/www/roxor-content-hub

# Copy files (from local via scp or git)
# Create venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copy .env
# Create systemd service
# Enable nginx site
# sudo systemctl enable roxor-content-hub
# sudo systemctl start roxor-content-hub
```

### Systemd service template
```ini
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
```

---

## Files NOT to touch

- `tools/content_tracker/services/akeneo.py`
- `shared/auth.py`, `shared/akeneo.py`, `shared/scaleflex.py`
- `tools/content_tracker/__init__.py`
