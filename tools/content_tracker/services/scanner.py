import os
import json
import sqlite3
import threading
from datetime import datetime

from tools.content_tracker.state import _scan_state, _scan_lock
from tools.content_tracker.services.akeneo import AkeneoClient

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR  = os.path.join(BASE_DIR, 'data')
DB_PATH   = os.path.join(DATA_DIR, 'tracker.db')


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _akeneo_client():
    return AkeneoClient({
        'base_url':      os.environ.get('AKENEO_URL', '').rstrip('/'),
        'client_id':     os.environ.get('AKENEO_CLIENT_ID', ''),
        'client_secret': os.environ.get('AKENEO_CLIENT_SECRET', ''),
        'username':      os.environ.get('AKENEO_USERNAME', ''),
        'password':      os.environ.get('AKENEO_PASSWORD', ''),
    })


_FALLBACK_ASSETS = [
    'cutout_1', 'cutout_2', 'line_drawing',
    'lifestyle_1', 'lifestyle_2', 'lifestyle_3', 'lifestyle_4', 'lifestyle_5', 'lifestyle_6',
    'fitting_instructions', 'nuie_web_cutout',
]


def _get_brand_config(brand):
    conn = _get_db()
    row  = conn.execute('SELECT required_attrs, required_assets FROM brand_config WHERE brand = ?', (brand,)).fetchone()
    conn.close()
    if not row:
        return {}, list(_FALLBACK_ASSETS)
    attrs  = json.loads(row['required_attrs']  or '{}')
    assets = json.loads(row['required_assets'] or '[]') or list(_FALLBACK_ASSETS)
    return attrs, assets


def _check_assets(product_values, asset_families):
    """Check Akeneo asset collection attributes. Returns {family: bool}."""
    result = {}
    for family in asset_families:
        val_list = product_values.get(family, [])
        result[family] = bool(val_list and val_list[0].get('data'))
    return result


def _check_content(product_values, required_attrs):
    """Check text/scopable attributes per scope. Returns {scope: {attr: bool}}."""
    result = {}
    for scope, attrs in required_attrs.items():
        result[scope] = {}
        for attr in attrs:
            val_list = product_values.get(attr, [])
            found = False
            for v in val_list:
                if v.get('scope') == scope:
                    data = v.get('data')
                    if data not in (None, '', [], {}):
                        found = True
                        break
            result[scope][attr] = found
    return result


def _fetch_products(brand, progress_ref):
    """Stream all products for brand from Akeneo. Mutates progress_ref dict with count/phase."""
    client = _akeneo_client()
    search = json.dumps({'brand': [{'operator': 'IN', 'value': [brand]}]})
    products = []
    for page in client.get_all_products_streaming(search=search):
        products.extend(page)
        progress_ref.update({
            'count': len(products),
            'phase': f'Fetching from Akeneo… {len(products)} products',
        })
    return products


def _build_sku_list(products):
    return [
        {
            'sku':    p['identifier'],
            'parent': p.get('parent') or p['identifier'],
            'family': p.get('family', ''),
            'values': p.get('values', {}),
        }
        for p in products if p.get('identifier')
    ]


# ── Asset scan ────────────────────────────────────────────────────────────────

def run_assets_scan(brand, scan_id):
    state = _scan_state.setdefault(brand, {})
    sub   = state.setdefault('assets', {})

    try:
        _, asset_families = _get_brand_config(brand)

        sub.update({'status': 'running', 'phase': 'Fetching from Akeneo…', 'count': 0})
        products   = _fetch_products(brand, sub)
        skus       = _build_sku_list(products)
        total_skus = len(skus)

        if not total_skus:
            sub.update({'status': 'complete', 'phase': 'No products found', 'count': 0})
            conn = _get_db()
            conn.execute('UPDATE scans SET status=?, completed_at=?, product_count=0 WHERE id=?',
                         ('complete', datetime.now().isoformat(), scan_id))
            conn.commit(); conn.close()
            return

        sub.update({'phase': f'Processing {total_skus} products…', 'count': total_skus})

        conn = _get_db()
        now  = datetime.now().isoformat()
        asset_totals = {f: 0 for f in asset_families}

        for item in skus:
            sku    = item['sku']
            values = item['values']
            assets = _check_assets(values, asset_families)

            for f, present in assets.items():
                if present:
                    asset_totals[f] += 1

            cs_cart_vals    = values.get('live_on_cs_cart', [])
            live_on_cs_cart = 1 if (cs_cart_vals and cs_cart_vals[0].get('data')) else 0

            existing = conn.execute(
                'SELECT content, content_scanned FROM product_coverage WHERE sku=?', (sku,)
            ).fetchone()

            conn.execute(
                '''INSERT OR REPLACE INTO product_coverage
                   (sku, brand, parent_model, akeneo_family, assets, content, last_scanned,
                    assets_scanned, content_scanned, live_on_cs_cart)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (sku, brand, item['parent'], item['family'],
                 json.dumps(assets),
                 existing['content']         if existing else '{}',
                 now, now,
                 existing['content_scanned'] if existing else None,
                 live_on_cs_cart)
            )

        stats_json = {f: round(asset_totals[f] / total_skus * 100) for f in asset_families}
        conn.execute(
            'INSERT INTO brand_stats (brand, scan_type, recorded_at, total_skus, stats_json) VALUES (?, ?, ?, ?, ?)',
            (brand, 'assets', now, total_skus, json.dumps(stats_json))
        )
        conn.execute('UPDATE scans SET status=?, completed_at=?, product_count=? WHERE id=?',
                     ('complete', now, total_skus, scan_id))
        conn.commit(); conn.close()

        sub.update({'status': 'complete', 'phase': f'Done — {total_skus} products', 'count': total_skus})

    except Exception as e:
        import traceback; traceback.print_exc()
        sub.update({'status': 'failed', 'error': str(e), 'phase': f'Failed: {e}'})
        try:
            conn = _get_db()
            conn.execute('UPDATE scans SET status=?, error=? WHERE id=?', ('failed', str(e), scan_id))
            conn.commit(); conn.close()
        except Exception:
            pass


# ── Content scan ──────────────────────────────────────────────────────────────

def run_content_scan(brand, scan_id):
    state = _scan_state.setdefault(brand, {})
    sub   = state.setdefault('content', {})

    try:
        required_attrs, _ = _get_brand_config(brand)
        if not required_attrs:
            sub.update({'status': 'complete', 'phase': 'No content config for this brand', 'count': 0})
            conn = _get_db()
            conn.execute('UPDATE scans SET status=?, completed_at=?, product_count=0 WHERE id=?',
                         ('complete', datetime.now().isoformat(), scan_id))
            conn.commit(); conn.close()
            return

        sub.update({'status': 'running', 'phase': 'Fetching from Akeneo…', 'count': 0})
        products   = _fetch_products(brand, sub)
        skus       = _build_sku_list(products)
        total_skus = len(skus)

        if not total_skus:
            sub.update({'status': 'complete', 'phase': 'No products found', 'count': 0})
            conn = _get_db()
            conn.execute('UPDATE scans SET status=?, completed_at=?, product_count=0 WHERE id=?',
                         ('complete', datetime.now().isoformat(), scan_id))
            conn.commit(); conn.close()
            return

        sub.update({'phase': f'Processing {total_skus} products…', 'count': total_skus})

        conn = _get_db()
        now  = datetime.now().isoformat()

        scope_totals = {s: {a: 0 for a in attrs} for s, attrs in required_attrs.items()}

        for item in skus:
            sku     = item['sku']
            values  = item['values']
            content = _check_content(values, required_attrs)

            for scope, attrs_result in content.items():
                for attr, present in attrs_result.items():
                    if present and scope in scope_totals and attr in scope_totals[scope]:
                        scope_totals[scope][attr] += 1

            existing = conn.execute(
                'SELECT assets, assets_scanned, live_on_cs_cart FROM product_coverage WHERE sku=?', (sku,)
            ).fetchone()

            conn.execute(
                '''INSERT OR REPLACE INTO product_coverage
                   (sku, brand, parent_model, akeneo_family, assets, content, last_scanned,
                    assets_scanned, content_scanned, live_on_cs_cart)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (sku, brand, item['parent'], item['family'],
                 existing['assets']         if existing else '{}',
                 json.dumps(content),
                 now,
                 existing['assets_scanned'] if existing else None,
                 now,
                 existing['live_on_cs_cart'] if existing else 0)
            )

        if total_skus > 0:
            stats = {}
            for scope, attr_map in scope_totals.items():
                for attr, n in attr_map.items():
                    stats[f'{scope}.{attr}'] = round(n / total_skus * 100)
            conn.execute(
                'INSERT INTO brand_stats (brand, scan_type, recorded_at, total_skus, stats_json) VALUES (?, ?, ?, ?, ?)',
                (brand, 'content', now, total_skus, json.dumps(stats))
            )

        conn.execute('UPDATE scans SET status=?, completed_at=?, product_count=? WHERE id=?',
                     ('complete', now, total_skus, scan_id))
        conn.commit(); conn.close()

        sub.update({'status': 'complete', 'phase': f'Done — {total_skus} products', 'count': total_skus})

    except Exception as e:
        import traceback; traceback.print_exc()
        sub.update({'status': 'failed', 'error': str(e), 'phase': f'Failed: {e}'})
        try:
            conn = _get_db()
            conn.execute('UPDATE scans SET status=?, error=? WHERE id=?', ('failed', str(e), scan_id))
            conn.commit(); conn.close()
        except Exception:
            pass


# ── Trigger helpers ───────────────────────────────────────────────────────────

def trigger_assets_scan(brand):
    with _scan_lock:
        state = _scan_state.setdefault(brand, {})
        if state.get('assets', {}).get('status') == 'running':
            return False, 'Asset scan already in progress'
        state.setdefault('assets', {}).update({'status': 'running', 'count': 0, 'phase': 'Starting…'})

    conn = _get_db()
    scan_id = conn.execute(
        'INSERT INTO scans (brand, status, scan_type, triggered_by, started_at) VALUES (?, ?, ?, ?, ?)',
        (brand, 'running', 'assets', 'manual', datetime.now().isoformat())
    ).lastrowid
    conn.commit(); conn.close()

    threading.Thread(target=run_assets_scan, args=(brand, scan_id), daemon=True).start()
    return True, scan_id


def trigger_content_scan(brand):
    with _scan_lock:
        state = _scan_state.setdefault(brand, {})
        if state.get('content', {}).get('status') == 'running':
            return False, 'Content scan already in progress'
        state.setdefault('content', {}).update({'status': 'running', 'count': 0, 'phase': 'Starting…'})

    conn = _get_db()
    scan_id = conn.execute(
        'INSERT INTO scans (brand, status, scan_type, triggered_by, started_at) VALUES (?, ?, ?, ?, ?)',
        (brand, 'running', 'content', 'manual', datetime.now().isoformat())
    ).lastrowid
    conn.commit(); conn.close()

    threading.Thread(target=run_content_scan, args=(brand, scan_id), daemon=True).start()
    return True, scan_id


def trigger_scan(brand):
    """Trigger both asset and content scans for a brand."""
    ok1, r1 = trigger_assets_scan(brand)
    ok2, r2 = trigger_content_scan(brand)
    return (ok1 or ok2), {'assets': r1, 'content': r2}


def trigger_scheduled_assets_scan(brand):
    with _scan_lock:
        state = _scan_state.setdefault(brand, {})
        if state.get('assets', {}).get('status') == 'running':
            return
        state.setdefault('assets', {}).update({'status': 'running', 'count': 0, 'phase': 'Starting (scheduled)…'})

    conn = _get_db()
    scan_id = conn.execute(
        'INSERT INTO scans (brand, status, scan_type, triggered_by, started_at) VALUES (?, ?, ?, ?, ?)',
        (brand, 'running', 'assets', 'scheduled', datetime.now().isoformat())
    ).lastrowid
    conn.commit(); conn.close()

    threading.Thread(target=run_assets_scan, args=(brand, scan_id), daemon=True).start()


def trigger_scheduled_content_scan(brand):
    with _scan_lock:
        state = _scan_state.setdefault(brand, {})
        if state.get('content', {}).get('status') == 'running':
            return
        state.setdefault('content', {}).update({'status': 'running', 'count': 0, 'phase': 'Starting (scheduled)…'})

    conn = _get_db()
    scan_id = conn.execute(
        'INSERT INTO scans (brand, status, scan_type, triggered_by, started_at) VALUES (?, ?, ?, ?, ?)',
        (brand, 'running', 'content', 'scheduled', datetime.now().isoformat())
    ).lastrowid
    conn.commit(); conn.close()

    threading.Thread(target=run_content_scan, args=(brand, scan_id), daemon=True).start()
