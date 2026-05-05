import csv
import io
import os
import json
import sqlite3
from datetime import datetime

from flask import render_template, request, jsonify, Response, redirect, url_for
from tools.content_tracker import content_tracker_bp
from shared.auth import tool_access_required
from tools.content_tracker.state import _scan_state, _scan_lock
from tools.content_tracker.services.scanner import (
    trigger_scan, trigger_assets_scan, trigger_content_scan,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, 'data')
DB_PATH   = os.path.join(DATA_DIR, 'tracker.db')
os.makedirs(DATA_DIR, exist_ok=True)

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
BRAND_NAMES = dict(BRANDS)

ASSET_LABELS = {
    'cutout_1': 'Cutout 1',               'cutout_2': 'Cutout 2',
    'line_drawing': 'Line Drawing',
    'lifestyle_1': 'LS 1',                'lifestyle_2': 'LS 2',      'lifestyle_3': 'LS 3',
    'lifestyle_4': 'LS 4',                'lifestyle_5': 'LS 5',      'lifestyle_6': 'LS 6',
    'premium_cutout': 'Prem. Cutout',
    'shopify_premium_image': 'Shopify Premium',
    'premium_asset_1': 'PA 1',            'premium_asset_2': 'PA 2',
    'premium_asset_3': 'PA 3',            'premium_asset_4': 'PA 4',
    'premium_asset_5': 'PA 5',            'premium_asset_6': 'PA 6',
    'premium_asset_7': 'PA 7',            'premium_asset_8': 'PA 8',
    'fitting_instructions': 'Fitting Inst.',
    'nuie_web_cutout': 'Nuie Web Cutout',
}

_BALTERLEY_ASSETS = [
    'cutout_1', 'shopify_premium_image', 'line_drawing',
    'lifestyle_1', 'lifestyle_2', 'lifestyle_3',
    'premium_asset_1', 'premium_asset_2', 'premium_asset_3', 'premium_asset_4',
    'premium_asset_5', 'premium_asset_6', 'premium_asset_7', 'premium_asset_8',
]
_OTHER_ASSETS = [
    'cutout_1', 'cutout_2', 'line_drawing',
    'lifestyle_1', 'lifestyle_2', 'lifestyle_3', 'lifestyle_4', 'lifestyle_5', 'lifestyle_6',
    'fitting_instructions', 'nuie_web_cutout',
]

DEFAULT_ASSET_CONFIGS = {'balterley': _BALTERLEY_ASSETS}
for _b in ['nuie', 'bc_designs', 'hudson_reed', 'bc_sanitan', 'bayswater', 'wickes', 'arley', 'arley_pro', 'synergy']:
    DEFAULT_ASSET_CONFIGS[_b] = _OTHER_ASSETS

# All families ever tracked (union of all brand configs) — for labels lookup
ASSET_FAMILIES = sorted(set(f for fams in DEFAULT_ASSET_CONFIGS.values() for f in fams))

_BULLET_SCOPES = ['amazon_seller', 'Tesco', 'Debenhams', 'b_and_q']
_BULLET_ATTRS  = [f'bullet_point_{i}' for i in range(1, 9)]

DEFAULT_CONFIGS = {
    'balterley': {
        'ecommerce':     ['title', 'description'],
        'shopify':       ['title', 'description'],
        'ebay':          ['title', 'description'],
        'amazon_seller': ['title', 'description'] + _BULLET_ATTRS,
        'Tesco':         ['title', 'description'] + _BULLET_ATTRS,
        'Debenhams':     ['title', 'description'] + _BULLET_ATTRS,
        'b_and_q':       ['title', 'description', 'Selling_Copy'] + _BULLET_ATTRS,
    },
}
_ECOMM_ONLY = {'ecommerce': ['title', 'description', 'features']}
for _b in ['nuie', 'bc_designs', 'hudson_reed', 'bc_sanitan', 'bayswater', 'wickes', 'arley', 'arley_pro', 'synergy']:
    DEFAULT_CONFIGS[_b] = _ECOMM_ONLY


# ── DB ────────────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute('''CREATE TABLE IF NOT EXISTS product_coverage (
        sku             TEXT PRIMARY KEY,
        brand           TEXT NOT NULL,
        parent_model    TEXT,
        akeneo_family   TEXT,
        assets          TEXT DEFAULT '{}',
        content         TEXT DEFAULT '{}',
        last_scanned    TEXT,
        assets_scanned  TEXT,
        content_scanned TEXT,
        live_on_cs_cart INTEGER DEFAULT 0
    )''')

    conn.execute('''CREATE TABLE IF NOT EXISTS scans (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        brand         TEXT NOT NULL,
        status        TEXT DEFAULT 'running',
        scan_type     TEXT DEFAULT 'assets',
        triggered_by  TEXT DEFAULT 'manual',
        product_count INTEGER DEFAULT 0,
        started_at    TEXT,
        completed_at  TEXT,
        error         TEXT
    )''')

    conn.execute('''CREATE TABLE IF NOT EXISTS brand_config (
        brand           TEXT PRIMARY KEY,
        required_attrs  TEXT DEFAULT '{}',
        required_assets TEXT DEFAULT '[]',
        updated_at      TEXT
    )''')

    conn.execute('''CREATE TABLE IF NOT EXISTS brand_stats (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        brand       TEXT NOT NULL,
        scan_type   TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        total_skus  INTEGER,
        stats_json  TEXT
    )''')

    # Live migrations — safe to run on existing DBs
    existing_pc = {row[1] for row in conn.execute('PRAGMA table_info(product_coverage)').fetchall()}
    for col, defn in [
        ('assets_scanned',  'TEXT'),
        ('content_scanned', 'TEXT'),
        ('live_on_cs_cart', 'INTEGER DEFAULT 0'),
    ]:
        if col not in existing_pc:
            conn.execute(f'ALTER TABLE product_coverage ADD COLUMN {col} {defn}')

    existing_sc = {row[1] for row in conn.execute('PRAGMA table_info(scans)').fetchall()}
    for col, defn in [
        ('scan_type',    "TEXT DEFAULT 'assets'"),
        ('triggered_by', "TEXT DEFAULT 'manual'"),
        ('error',        'TEXT'),
    ]:
        if col not in existing_sc:
            conn.execute(f'ALTER TABLE scans ADD COLUMN {col} {defn}')

    existing_bc = {row[1] for row in conn.execute('PRAGMA table_info(brand_config)').fetchall()}
    if 'required_assets' not in existing_bc:
        conn.execute("ALTER TABLE brand_config ADD COLUMN required_assets TEXT DEFAULT '[]'")

    # Seed default brand configs
    for brand, cfg in DEFAULT_CONFIGS.items():
        asset_cfg = DEFAULT_ASSET_CONFIGS.get(brand, _OTHER_ASSETS)
        if not conn.execute('SELECT 1 FROM brand_config WHERE brand = ?', (brand,)).fetchone():
            conn.execute(
                'INSERT INTO brand_config (brand, required_attrs, required_assets, updated_at) VALUES (?, ?, ?, ?)',
                (brand, json.dumps(cfg), json.dumps(asset_cfg), datetime.now().isoformat())
            )
        else:
            # Update required_assets for existing rows that have empty/default value
            existing = conn.execute('SELECT required_assets FROM brand_config WHERE brand=?', (brand,)).fetchone()
            if not existing or existing['required_assets'] in (None, '[]', '{}', ''):
                conn.execute(
                    'UPDATE brand_config SET required_assets=?, updated_at=? WHERE brand=?',
                    (json.dumps(asset_cfg), datetime.now().isoformat(), brand)
                )

    conn.commit()
    conn.close()


init_db()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_brand_config(brand):
    conn = get_db()
    row  = conn.execute('SELECT required_attrs, required_assets FROM brand_config WHERE brand = ?', (brand,)).fetchone()
    conn.close()
    if not row:
        return {}, DEFAULT_ASSET_CONFIGS.get(brand, _OTHER_ASSETS)
    attrs  = json.loads(row['required_attrs']  or '{}')
    assets = json.loads(row['required_assets'] or '[]') or DEFAULT_ASSET_CONFIGS.get(brand, _OTHER_ASSETS)
    return attrs, assets


def _content_coverage(skus, required_attrs):
    total = passed = 0
    for sku in skus:
        content = sku.get('content', {})
        for scope, attrs in required_attrs.items():
            for attr in attrs:
                total += 1
                if content.get(scope, {}).get(attr):
                    passed += 1
    return passed, total


def _build_models(rows, required_attrs, brand_asset_families=None):
    """Group DB rows into models dict with aggregated asset/content data."""
    if brand_asset_families is None:
        brand_asset_families = ASSET_FAMILIES
    models = {}
    for row in rows:
        model = row['parent_model'] or row['sku']
        if model not in models:
            models[model] = {
                'skus':         [],
                'asset_totals': {f: 0 for f in brand_asset_families},
                'count':        0,
                'cs_cart_count': 0,
            }
        assets  = json.loads(row['assets']  or '{}')
        content = json.loads(row['content'] or '{}')
        cs_cart = int(row['live_on_cs_cart'] or 0)
        models[model]['skus'].append({
            'sku': row['sku'], 'assets': assets, 'content': content, 'cs_cart': cs_cart,
        })
        models[model]['count'] += 1
        if cs_cart:
            models[model]['cs_cart_count'] += 1
        for f, present in assets.items():
            if present and f in models[model]['asset_totals']:
                models[model]['asset_totals'][f] += 1

    for model_data in models.values():
        passed, total = _content_coverage(model_data['skus'], required_attrs)
        model_data['content_pct'] = round(passed / total * 100) if total else None

    return models


def _compute_chart_data(models_list, total_skus, active_families, required_attrs):
    """Return chart data dicts for imagery and content tabs."""
    # Imagery bar: % of SKUs with each active family
    asset_pcts = {}
    for f in active_families:
        n = sum(m['asset_totals'].get(f, 0) for _, m in models_list)
        asset_pcts[f] = round(n / total_skus * 100) if total_skus else 0

    # Imagery donut: fully imaged (has cutout_1) vs rest
    has_cutout1 = sum(m['asset_totals'].get('cutout_1', 0) for _, m in models_list)
    donut_data  = {
        'imaged':   has_cutout1,
        'missing':  total_skus - has_cutout1,
        'pct':      round(has_cutout1 / total_skus * 100) if total_skus else 0,
    }

    # Imagery worst models (lowest avg asset coverage %)
    def model_asset_pct(item):
        code, m = item
        if not active_families or not m['count']:
            return 100
        total_checks = len(active_families) * m['count']
        total_present = sum(m['asset_totals'].get(f, 0) for f in active_families)
        return round(total_present / total_checks * 100)

    worst_assets = sorted(
        [(code, model_asset_pct((code, m))) for code, m in models_list],
        key=lambda x: x[1]
    )[:10]

    # Content bar: % complete per scope
    content_scope_pcts = {}
    if required_attrs:
        all_skus = [sku for _, m in models_list for sku in m['skus']]
        for scope, attrs in required_attrs.items():
            if not attrs or not all_skus:
                continue
            passed = sum(1 for sku in all_skus for attr in attrs if sku['content'].get(scope, {}).get(attr))
            content_scope_pcts[scope] = round(passed / (len(all_skus) * len(attrs)) * 100)

    # Content worst models
    worst_content = sorted(
        [(code, m['content_pct'] or 0) for code, m in models_list if m['content_pct'] is not None],
        key=lambda x: x[1]
    )[:10]

    return {
        'asset_pcts':         asset_pcts,
        'donut':              donut_data,
        'worst_assets':       worst_assets,
        'content_scope_pcts': content_scope_pcts,
        'worst_content':      worst_content,
    }


def _gap_counts(models_list, active_families, required_attrs):
    asset_gaps   = 0
    content_gaps = 0
    for _, m in models_list:
        for sku in m['skus']:
            if sku['assets']:   # only count if scanned
                asset_gaps += sum(1 for f in active_families if sku['assets'].get(f) is False)
            for scope, attrs in required_attrs.items():
                content_gaps += sum(1 for attr in attrs if not sku['content'].get(scope, {}).get(attr))
    return asset_gaps, content_gaps


# ── Views ─────────────────────────────────────────────────────────────────────

@content_tracker_bp.route('/')
@tool_access_required('content_tracker')
def index():
    return redirect(url_for('content_tracker.imagery_view'))


def _brand_base_rows(conn):
    """Shared brand data loader used by both imagery and content views."""
    brands_data = []
    for code, name in BRANDS:
        row = conn.execute(
            'SELECT COUNT(DISTINCT parent_model) as models, COUNT(*) as skus FROM product_coverage WHERE brand=?',
            (code,)
        ).fetchone()
        state         = _scan_state.get(code, {})
        brands_data.append({
            'code':          code,
            'name':          name,
            'sku_count':     row['skus']   if row else 0,
            'model_count':   row['models'] if row else 0,
            '_state':        state,
        })
    return brands_data


@content_tracker_bp.route('/imagery')
@tool_access_required('content_tracker')
def imagery_view():
    conn = get_db()
    brands_data = _brand_base_rows(conn)

    for b in brands_data:
        code          = b['code']
        last_scan     = conn.execute(
            "SELECT completed_at FROM scans WHERE brand=? AND scan_type='assets' AND status='complete' ORDER BY id DESC LIMIT 1",
            (code,)
        ).fetchone()
        assets_state  = b['_state'].get('assets', {})

        # Quick cutout_1 coverage %
        cutout1_pct = None
        if b['sku_count'] > 0:
            rows = conn.execute(
                "SELECT assets FROM product_coverage WHERE brand=?", (code,)
            ).fetchall()
            has = sum(1 for r in rows if json.loads(r['assets'] or '{}').get('cutout_1'))
            cutout1_pct = round(has / len(rows) * 100) if rows else None

        b.update({
            'last_assets_scan': (last_scan['completed_at'] or '')[:10] if last_scan else None,
            'assets_scanning':  assets_state.get('status') == 'running',
            'assets_phase':     assets_state.get('phase', ''),
            'cutout1_pct':      cutout1_pct,
        })
        del b['_state']

    conn.close()
    return render_template('content_tracker/imagery.html', brands=brands_data)


@content_tracker_bp.route('/content')
@tool_access_required('content_tracker')
def content_view():
    conn = get_db()
    brands_data = _brand_base_rows(conn)

    for b in brands_data:
        code          = b['code']
        last_scan     = conn.execute(
            "SELECT completed_at FROM scans WHERE brand=? AND scan_type='content' AND status='complete' ORDER BY id DESC LIMIT 1",
            (code,)
        ).fetchone()
        content_state = b['_state'].get('content', {})
        required_attrs, _ = _get_brand_config(code)
        scopes = list(required_attrs.keys())

        # Overall content coverage %
        content_pct = None
        if b['sku_count'] > 0 and required_attrs:
            rows    = conn.execute("SELECT content FROM product_coverage WHERE brand=?", (code,)).fetchall()
            passed  = total = 0
            for r in rows:
                c = json.loads(r['content'] or '{}')
                for scope, attrs in required_attrs.items():
                    for attr in attrs:
                        total  += 1
                        if c.get(scope, {}).get(attr):
                            passed += 1
            content_pct = round(passed / total * 100) if total else None

        b.update({
            'last_content_scan': (last_scan['completed_at'] or '')[:10] if last_scan else None,
            'content_scanning':  content_state.get('status') == 'running',
            'content_phase':     content_state.get('phase', ''),
            'content_pct':       content_pct,
            'scopes':            scopes,
        })
        del b['_state']

    conn.close()
    return render_template('content_tracker/content.html', brands=brands_data)


@content_tracker_bp.route('/brand/<brand_code>')
@tool_access_required('content_tracker')
def brand_view(brand_code):
    if brand_code not in BRAND_NAMES:
        return 'Brand not found', 404

    required_attrs, brand_asset_families = _get_brand_config(brand_code)
    conn  = get_db()
    rows  = conn.execute(
        'SELECT * FROM product_coverage WHERE brand=? ORDER BY parent_model, sku',
        (brand_code,)
    ).fetchall()
    conn.close()

    models      = _build_models(rows, required_attrs, brand_asset_families)
    models_list = sorted(models.items())

    active_families = [
        f for f in brand_asset_families
        if any(m['asset_totals'].get(f, 0) > 0 for _, m in models_list)
    ]

    total_skus    = len(rows)
    cs_cart_count = sum(int(r['live_on_cs_cart'] or 0) for r in rows)

    chart_data   = _compute_chart_data(models_list, total_skus, active_families, required_attrs)
    asset_gaps, content_gaps = _gap_counts(models_list, active_families, required_attrs)

    state         = _scan_state.get(brand_code, {})
    assets_state  = state.get('assets',  {})
    content_state = state.get('content', {})

    return render_template('content_tracker/brand.html',
        brand_code=brand_code,
        brand_name=BRAND_NAMES[brand_code],
        models=models_list,
        active_families=active_families,
        asset_labels=ASSET_LABELS,
        required_attrs=required_attrs,
        total_models=len(models),
        total_skus=total_skus,
        cs_cart_count=cs_cart_count,
        chart_data=chart_data,
        asset_gap_count=asset_gaps,
        content_gap_count=content_gaps,
        assets_scanning=assets_state.get('status')  == 'running',
        assets_phase=assets_state.get('phase',  ''),
        content_scanning=content_state.get('status') == 'running',
        content_phase=content_state.get('phase', ''),
    )


@content_tracker_bp.route('/brand/<brand_code>/gaps')
@tool_access_required('content_tracker')
def gaps_view(brand_code):
    if brand_code not in BRAND_NAMES:
        return 'Brand not found', 404

    required_attrs, brand_asset_families = _get_brand_config(brand_code)
    conn  = get_db()
    rows  = conn.execute(
        'SELECT * FROM product_coverage WHERE brand=? ORDER BY parent_model, sku',
        (brand_code,)
    ).fetchall()
    conn.close()

    content_gaps = []
    asset_gaps   = []

    for row in rows:
        sku    = row['sku']
        model  = row['parent_model'] or sku
        cat    = row['akeneo_family'] or ''
        assets = json.loads(row['assets']  or '{}')
        content = json.loads(row['content'] or '{}')

        for scope, attrs in required_attrs.items():
            for attr in attrs:
                if not content.get(scope, {}).get(attr):
                    content_gaps.append({
                        'sku': sku, 'model': model, 'category': cat,
                        'scope': scope, 'attribute': attr,
                    })

        if assets:   # only show asset gaps if scanned
            for family in brand_asset_families:
                if assets.get(family) is False:
                    asset_gaps.append({
                        'sku': sku, 'model': model, 'category': cat,
                        'asset_family': family,
                    })

    # Unique filter values
    content_categories = sorted({g['category'] for g in content_gaps})
    content_scopes     = sorted({g['scope']    for g in content_gaps})
    asset_categories   = sorted({g['category'] for g in asset_gaps})
    asset_families_present = sorted({g['asset_family'] for g in asset_gaps})

    return render_template('content_tracker/gaps.html',
        brand_code=brand_code,
        brand_name=BRAND_NAMES[brand_code],
        content_gaps=content_gaps,
        asset_gaps=asset_gaps,
        content_categories=content_categories,
        content_scopes=content_scopes,
        asset_categories=asset_categories,
        asset_families_present=asset_families_present,
        asset_labels=ASSET_LABELS,
    )


@content_tracker_bp.route('/config')
@tool_access_required('content_tracker')
def config_view():
    conn = get_db()
    configs = {}
    for code, name in BRANDS:
        row = conn.execute('SELECT required_attrs, required_assets FROM brand_config WHERE brand=?', (code,)).fetchone()
        configs[code] = {
            'name':         name,
            'json':         json.dumps(json.loads(row['required_attrs'] or '{}'), indent=2) if row else '{}',
            'assets_json':  json.dumps(json.loads(row['required_assets'] or '[]'), indent=2) if row else '[]',
        }
    conn.close()
    return render_template('content_tracker/config.html', configs=configs, brands=BRANDS)


@content_tracker_bp.route('/model/<path:model_code>')
@tool_access_required('content_tracker')
def model_view(model_code):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM product_coverage WHERE parent_model=? ORDER BY sku',
        (model_code,)
    ).fetchall()
    if not rows:
        rows = conn.execute(
            'SELECT * FROM product_coverage WHERE sku=? AND (parent_model=sku OR parent_model IS NULL)',
            (model_code,)
        ).fetchall()
    if not rows:
        conn.close()
        return 'Model not found', 404

    brand_code                       = rows[0]['brand']
    required_attrs, brand_asset_fams = _get_brand_config(brand_code)
    conn.close()

    skus       = []
    fam_totals = {f: 0 for f in brand_asset_fams}
    for row in rows:
        assets  = json.loads(row['assets']  or '{}')
        content = json.loads(row['content'] or '{}')
        for f, present in assets.items():
            if present and f in fam_totals:
                fam_totals[f] += 1
        skus.append({'sku': row['sku'], 'assets': assets, 'content': content})

    active_families = [f for f in brand_asset_fams if fam_totals.get(f, 0) > 0 or
                       any(s['assets'].get(f) is False for s in skus)]
    active_scopes   = [s for s in required_attrs if any(s in sku['content'] for sku in skus)]

    content_passed, content_total = _content_coverage(skus, required_attrs)

    total_cols = 1 + sum(len(required_attrs[s]) for s in active_scopes)

    return render_template('content_tracker/model.html',
        model_code=model_code,
        brand_code=brand_code,
        brand_name=BRAND_NAMES.get(brand_code, brand_code),
        skus=skus,
        active_families=active_families,
        asset_labels=ASSET_LABELS,
        fam_totals=fam_totals,
        required_attrs=required_attrs,
        active_scopes=active_scopes,
        content_passed=content_passed,
        content_total=content_total,
        total=len(skus),
        total_cols=total_cols,
    )


# ── API ───────────────────────────────────────────────────────────────────────

@content_tracker_bp.route('/api/scan', methods=['POST'])
@tool_access_required('content_tracker')
def start_scan():
    brand = (request.json or {}).get('brand')
    if brand not in BRAND_NAMES:
        return jsonify({'error': 'Invalid brand'}), 400
    ok, result = trigger_scan(brand)
    if not ok:
        return jsonify({'error': 'Both scans already in progress'}), 409
    return jsonify({'success': True, 'scan_ids': result})


@content_tracker_bp.route('/api/scan/assets', methods=['POST'])
@tool_access_required('content_tracker')
def start_assets_scan():
    brand = (request.json or {}).get('brand')
    if brand not in BRAND_NAMES:
        return jsonify({'error': 'Invalid brand'}), 400
    ok, result = trigger_assets_scan(brand)
    if not ok:
        return jsonify({'error': result}), 409
    return jsonify({'success': True, 'scan_id': result})


@content_tracker_bp.route('/api/scan/content', methods=['POST'])
@tool_access_required('content_tracker')
def start_content_scan():
    brand = (request.json or {}).get('brand')
    if brand not in BRAND_NAMES:
        return jsonify({'error': 'Invalid brand'}), 400
    ok, result = trigger_content_scan(brand)
    if not ok:
        return jsonify({'error': result}), 409
    return jsonify({'success': True, 'scan_id': result})


@content_tracker_bp.route('/api/scan/status')
@tool_access_required('content_tracker')
def scan_status():
    brand = request.args.get('brand')
    if brand:
        state = _scan_state.get(brand, {})
        return jsonify({
            'assets':  state.get('assets',  {'status': 'idle'}),
            'content': state.get('content', {'status': 'idle'}),
        })
    return jsonify({
        b: {
            'assets':  s.get('assets',  {'status': 'idle'}),
            'content': s.get('content', {'status': 'idle'}),
        }
        for b, s in _scan_state.items()
    })


@content_tracker_bp.route('/api/config/<brand>', methods=['GET', 'POST'])
@tool_access_required('content_tracker')
def brand_config(brand):
    if brand not in BRAND_NAMES:
        return jsonify({'error': 'Invalid brand'}), 400
    conn = get_db()
    if request.method == 'POST':
        data = request.json or {}
        try:
            attrs  = data.get('required_attrs', {})
            assets = data.get('required_assets', [])
            json.dumps(attrs); json.dumps(assets)
        except (TypeError, ValueError):
            conn.close()
            return jsonify({'error': 'Invalid JSON'}), 400
        conn.execute(
            'INSERT OR REPLACE INTO brand_config (brand, required_attrs, required_assets, updated_at) VALUES (?, ?, ?, ?)',
            (brand, json.dumps(attrs), json.dumps(assets), datetime.now().isoformat())
        )
        conn.commit(); conn.close()
        return jsonify({'success': True})
    row = conn.execute('SELECT required_attrs, required_assets FROM brand_config WHERE brand=?', (brand,)).fetchone()
    conn.close()
    return jsonify({
        'required_attrs':  json.loads(row['required_attrs']  or '{}') if row else {},
        'required_assets': json.loads(row['required_assets'] or '[]') if row else [],
    })


@content_tracker_bp.route('/api/brand-stats')
@tool_access_required('content_tracker')
def brand_stats():
    brand = request.args.get('brand')
    if not brand:
        return jsonify({'error': 'brand required'}), 400
    conn  = get_db()
    rows  = conn.execute('SELECT assets FROM product_coverage WHERE brand=?', (brand,)).fetchall()
    conn.close()
    if not rows:
        return jsonify({'skus': 0, 'coverage': {}})
    totals = {f: 0 for f in ASSET_FAMILIES}
    for row in rows:
        assets = json.loads(row['assets'] or '{}')
        for f in ASSET_FAMILIES:
            if assets.get(f):
                totals[f] += 1
    n = len(rows)
    coverage = {f: round(totals[f] / n * 100) for f in ASSET_FAMILIES if totals[f] > 0}
    return jsonify({'skus': n, 'coverage': coverage})


@content_tracker_bp.route('/api/trend/<brand>')
@tool_access_required('content_tracker')
def brand_trend(brand):
    if brand not in BRAND_NAMES:
        return jsonify({'error': 'Invalid brand'}), 400
    scan_type = request.args.get('type', 'assets')
    conn  = get_db()
    rows  = conn.execute(
        'SELECT recorded_at, total_skus, stats_json FROM brand_stats WHERE brand=? AND scan_type=? ORDER BY id DESC LIMIT 30',
        (brand, scan_type)
    ).fetchall()
    conn.close()
    return jsonify([
        {'date': r['recorded_at'][:10], 'total_skus': r['total_skus'], 'stats': json.loads(r['stats_json'] or '{}')}
        for r in reversed(rows)
    ])


@content_tracker_bp.route('/api/export/<brand_code>/content')
@tool_access_required('content_tracker')
def export_content_gaps(brand_code):
    if brand_code not in BRAND_NAMES:
        return 'Brand not found', 404
    required_attrs, _ = _get_brand_config(brand_code)
    conn  = get_db()
    rows  = conn.execute('SELECT * FROM product_coverage WHERE brand=? ORDER BY parent_model, sku', (brand_code,)).fetchall()
    conn.close()

    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(['sku', 'parent_model', 'category', 'scope', 'attribute'])
    for row in rows:
        content = json.loads(row['content'] or '{}')
        for scope, attrs in required_attrs.items():
            for attr in attrs:
                if not content.get(scope, {}).get(attr):
                    w.writerow([row['sku'], row['parent_model'] or row['sku'], row['akeneo_family'] or '', scope, attr])

    return Response(
        out.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={brand_code}_content_gaps.csv'},
    )


@content_tracker_bp.route('/api/export/<brand_code>/assets')
@tool_access_required('content_tracker')
def export_asset_gaps(brand_code):
    if brand_code not in BRAND_NAMES:
        return 'Brand not found', 404
    _, brand_asset_families = _get_brand_config(brand_code)
    conn  = get_db()
    rows  = conn.execute('SELECT * FROM product_coverage WHERE brand=? ORDER BY parent_model, sku', (brand_code,)).fetchall()
    conn.close()

    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(['sku', 'parent_model', 'category', 'asset_family'])
    for row in rows:
        assets = json.loads(row['assets'] or '{}')
        if not assets:
            continue
        for family in brand_asset_families:
            if assets.get(family) is False:
                w.writerow([row['sku'], row['parent_model'] or row['sku'], row['akeneo_family'] or '', family])

    return Response(
        out.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={brand_code}_asset_gaps.csv'},
    )


@content_tracker_bp.route('/api/scheduler/status')
@tool_access_required('content_tracker')
def scheduler_status():
    try:
        from tools.content_tracker.services.scheduler import get_job_info
        return jsonify(get_job_info())
    except Exception as e:
        return jsonify({'error': str(e)}), 500
