import os
import sqlite3
import uuid
import base64
import re
from datetime import datetime, timedelta

import fitz
import requests
from flask import render_template, request, jsonify, send_from_directory

from tools.cutouts import cutouts_bp
from shared.auth import tool_access_required

# ── Paths ────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(BASE_DIR, 'data')
PENDING_DIR = os.path.join(DATA_DIR, 'pending')
DB_PATH     = os.path.join(DATA_DIR, 'cutouts.db')
os.makedirs(PENDING_DIR, exist_ok=True)

ZIP_EXCLUDED_BRANDS = {'balterley'}

# ── Database ─────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS pending_reviews (
        id TEXT PRIMARY KEY,
        sku TEXT NOT NULL,
        source_filename TEXT NOT NULL,
        jpg_filename TEXT NOT NULL,
        cutout_url TEXT DEFAULT '',
        pdf_id TEXT DEFAULT '',
        asset_type TEXT DEFAULT 'ld',
        brand TEXT DEFAULT '',
        scaleflex_url TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        created_at TEXT NOT NULL
    )''')
    cols = [r[1] for r in conn.execute('PRAGMA table_info(pending_reviews)').fetchall()]
    for col, defval in [('pdf_id', "''"), ('asset_type', "'ld'"), ('brand', "''"), ('scaleflex_url', "''")]:
        if col not in cols:
            conn.execute(f"ALTER TABLE pending_reviews ADD COLUMN {col} TEXT DEFAULT {defval}")
    conn.commit()
    conn.close()


init_db()

# ── Akeneo ───────────────────────────────────────────────

_token = None
_token_expiry = None


def _akeneo_token():
    global _token, _token_expiry
    if _token and _token_expiry and datetime.now() < _token_expiry:
        return _token
    url        = os.environ.get('AKENEO_URL', '').rstrip('/')
    client_id  = os.environ.get('AKENEO_CLIENT_ID', '')
    secret     = os.environ.get('AKENEO_CLIENT_SECRET', '')
    username   = os.environ.get('AKENEO_USERNAME', '')
    password   = os.environ.get('AKENEO_PASSWORD', '')
    if not all([url, client_id, secret, username, password]):
        return None
    auth = base64.b64encode(f'{client_id}:{secret}'.encode()).decode()
    resp = requests.post(
        f'{url}/api/oauth/v1/token',
        json={'grant_type': 'password', 'username': username, 'password': password},
        headers={'Content-Type': 'application/json', 'Authorization': f'Basic {auth}'}
    )
    if resp.status_code != 200:
        return None
    data = resp.json()
    _token = data['access_token']
    _token_expiry = datetime.now() + timedelta(seconds=data['expires_in'] - 60)
    return _token


def akeneo_product_info(sku):
    token = _akeneo_token()
    url = os.environ.get('AKENEO_URL', '').rstrip('/')
    if not token:
        return {'cutout_url': '', 'parent': None, 'brand': 'Unknown'}
    try:
        resp = requests.get(
            f'{url}/api/rest/v1/products/{requests.utils.quote(sku, safe="")}',
            headers={'Authorization': f'Bearer {token}'}
        )
        if resp.status_code != 200:
            return {'cutout_url': '', 'parent': None, 'brand': 'Unknown'}
        product = resp.json()
        values  = product.get('values', {})
        brand   = 'Unknown'
        for attr in ['brand', 'marque', 'brand_name']:
            if attr in values:
                for entry in values[attr]:
                    if entry.get('data'):
                        brand = entry['data']
                        break
                if brand != 'Unknown':
                    break
        if brand == 'Unknown':
            brand = product.get('family', 'Unknown')
        parent     = product.get('parent')
        cutout_url = ''
        cutout_codes = None
        for entry in values.get('cutout_1', []):
            if entry.get('data'):
                cutout_codes = entry['data']
                break
        if cutout_codes and isinstance(cutout_codes, list):
            resp2 = requests.get(
                f'{url}/api/rest/v1/asset-families/cutout_1/assets/{cutout_codes[0]}',
                headers={'Authorization': f'Bearer {token}'}
            )
            if resp2.status_code == 200:
                for vals in resp2.json().get('values', {}).values():
                    for v in vals:
                        if v.get('attribute_type') == 'media_link' and v.get('data'):
                            cutout_url = v['data']
                            break
                    if cutout_url:
                        break
        return {'cutout_url': cutout_url, 'parent': parent, 'brand': brand}
    except Exception:
        return {'cutout_url': '', 'parent': None, 'brand': 'Unknown'}


def akeneo_siblings(parent_code):
    token = _akeneo_token()
    url = os.environ.get('AKENEO_URL', '').rstrip('/')
    if not token:
        return []
    identifiers = []
    try:
        next_url = f'{url}/api/rest/v1/products'
        params   = {'search': f'{{"parent":[{{"operator":"=","value":"{parent_code}"}}]}}', 'limit': 100}
        while next_url:
            resp = requests.get(next_url, headers={'Authorization': f'Bearer {token}'}, params=params)
            if resp.status_code != 200:
                break
            data = resp.json()
            identifiers.extend(i['identifier'] for i in data.get('_embedded', {}).get('items', []))
            next_url = data.get('_links', {}).get('next', {}).get('href')
            params   = None
    except Exception:
        pass
    return identifiers


def expand_skus(skus, cache=None):
    cache = cache or {}
    expanded   = {}
    seen_parents = {}
    for sku in skus:
        if sku in cache:
            parent = cache[sku].get('parent')
        else:
            cache[sku] = akeneo_product_info(sku)
            parent = cache[sku].get('parent')
        if not parent:
            expanded[sku] = [sku]
            continue
        if parent in seen_parents:
            expanded[sku] = seen_parents[parent]
            continue
        siblings = akeneo_siblings(parent) or [sku]
        seen_parents[parent] = siblings
        expanded[sku] = siblings
    return expanded

# ── PDF / Scaleflex ──────────────────────────────────────

def pdf_to_jpg(pdf_bytes, dpi=300):
    doc  = fitz.open(stream=pdf_bytes, filetype='pdf')
    page = doc[0]
    zoom = dpi / 72
    mat  = fitz.Matrix(zoom, zoom)
    pix  = page.get_pixmap(matrix=mat)
    jpg  = pix.tobytes('jpeg', jpg_quality=95)
    doc.close()
    return jpg


def upload_to_scaleflex(jpg_path, filename):
    api_key   = os.environ.get('SCALEFLEX_API_KEY', '')
    workspace = os.environ.get('SCALEFLEX_WORKSPACE', 'xa38qjmpah')
    sf_url    = f'https://api.filerobot.com/{workspace}/v4/files'
    if not api_key:
        return {'success': False, 'error': 'No Scaleflex API key', 'cdn_url': ''}
    try:
        with open(jpg_path, 'rb') as f:
            resp = requests.post(
                sf_url,
                headers={'X-Filerobot-Key': api_key},
                files={'file': (filename, f, 'image/jpeg')},
                params={'folder': '/'},
                timeout=120
            )
        data = resp.json()
        if resp.status_code == 403 and data.get('code') == 'SAME_ASSET_EXISTS_SKIP_UPLOAD':
            with open(jpg_path, 'rb') as f:
                resp2 = requests.post(
                    sf_url,
                    headers={'X-Filerobot-Key': api_key},
                    files={'file': (filename, f, 'image/jpeg')},
                    params={'folder': '/', 'allow_same_file_name': 'false', 'obey_deduplicate': 'false'},
                    timeout=120
                )
            if resp2.status_code == 200:
                data = resp2.json()
        cdn_url = _cdn_url(data, filename)
        return {'success': True, 'cdn_url': cdn_url}
    except Exception as e:
        return {'success': False, 'error': str(e), 'cdn_url': ''}


def _cdn_url(data, filename):
    try:
        url_data = data.get('file', data).get('url', {})
        if isinstance(url_data, dict):
            cdn = url_data.get('cdn', '') or url_data.get('public', '')
            if cdn:
                return cdn
        elif isinstance(url_data, str) and url_data:
            return url_data
    except Exception:
        pass
    return f'https://files.roxorgroup.com/{filename}'


def clean_sku(sku):
    return re.sub(r'_(co\d*|ld|ls\d+|front|top|side|back)$', '', sku, flags=re.IGNORECASE)


def parse_skus(filename):
    name = filename.rsplit('.', 1)[0] if '.' in filename else filename
    return [clean_sku(s.strip()) for s in name.split(',') if s.strip()]


def cleanup_pdf(conn, pdf_id):
    if not pdf_id:
        return
    remaining = conn.execute(
        'SELECT COUNT(*) FROM pending_reviews WHERE pdf_id = ? AND status = ?', (pdf_id, 'pending')
    ).fetchone()[0]
    if remaining == 0:
        pdf_path = os.path.join(PENDING_DIR, f'{pdf_id}.pdf')
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

# ── Routes ───────────────────────────────────────────────

@cutouts_bp.route('/')
@tool_access_required('cutouts')
def index():
    return render_template('cutouts/index.html', tab='upload')


@cutouts_bp.route('/review')
@tool_access_required('cutouts')
def review():
    return render_template('cutouts/index.html', tab='review')


@cutouts_bp.route('/api/process', methods=['POST'])
@tool_access_required('cutouts')
def process_files():
    if 'files' not in request.files:
        return jsonify({'error': 'No files uploaded'}), 400
    files      = request.files.getlist('files')
    asset_type = request.form.get('asset_type', 'ld')
    if asset_type not in ('ld', 'co'):
        asset_type = 'ld'
    results    = []
    conn       = get_db()
    for uploaded_file in files:
        filename = uploaded_file.filename or 'unknown'
        if asset_type == 'ld':
            if not filename.lower().endswith(('.pdf', '.jpg', '.jpeg')):
                results.append({'filename': filename, 'skus': [], 'status': 'error', 'message': 'Not a PDF or JPG'})
                continue
        else:
            if not filename.lower().endswith(('.jpg', '.jpeg')):
                results.append({'filename': filename, 'skus': [], 'status': 'error', 'message': 'Not a JPG'})
                continue
        skus = parse_skus(filename)
        if not skus:
            results.append({'filename': filename, 'skus': [], 'status': 'error', 'message': 'No SKUs in filename'})
            continue
        try:
            file_bytes = uploaded_file.read()
            jpg_bytes  = pdf_to_jpg(file_bytes) if asset_type == 'ld' and filename.lower().endswith('.pdf') else file_bytes
        except Exception as e:
            results.append({'filename': filename, 'skus': skus, 'status': 'error', 'message': str(e)})
            continue
        pdf_id = ''
        if asset_type == 'ld' and filename.lower().endswith('.pdf'):
            pdf_id = str(uuid.uuid4())
            with open(os.path.join(PENDING_DIR, f'{pdf_id}.pdf'), 'wb') as f:
                f.write(file_bytes)
        cache    = {sku: akeneo_product_info(sku) for sku in skus}
        expanded = expand_skus(skus, cache)
        all_skus = []
        seen     = set()
        for sku in skus:
            for related in expanded.get(sku, [sku]):
                if related not in seen:
                    seen.add(related)
                    all_skus.append(related)
        suffix      = '_ld' if asset_type == 'ld' else '_co1'
        sku_results = []
        for sku in all_skus:
            review_id = str(uuid.uuid4())
            jpg_fn    = f'{sku}{suffix}.jpg'
            with open(os.path.join(PENDING_DIR, f'{review_id}.jpg'), 'wb') as f:
                f.write(jpg_bytes)
            info = cache.get(sku) or akeneo_product_info(sku)
            conn.execute(
                'INSERT INTO pending_reviews (id, sku, source_filename, jpg_filename, cutout_url, pdf_id, asset_type, brand, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (review_id, sku, filename, jpg_fn, info['cutout_url'], pdf_id, asset_type, info['brand'], 'pending', datetime.now().isoformat())
            )
            sku_results.append({'sku': sku, 'filename': jpg_fn, 'success': True, 'has_cutout': bool(info['cutout_url'])})
        conn.commit()
        extra = len(all_skus) - len(skus)
        msg   = f'{len(sku_results)} SKU{"s" if len(sku_results) != 1 else ""} ready for review'
        if extra > 0:
            msg += f' ({extra} added from parent model)'
        results.append({'filename': filename, 'skus': skus, 'sku_results': sku_results, 'status': 'success', 'message': msg})
    conn.close()
    return jsonify({'results': results})


@cutouts_bp.route('/api/pending')
@tool_access_required('cutouts')
def get_pending():
    conn  = get_db()
    rows  = conn.execute('SELECT * FROM pending_reviews WHERE status = ? ORDER BY created_at DESC', ('pending',)).fetchall()
    conn.close()
    return jsonify({'items': [dict(r) for r in rows]})


@cutouts_bp.route('/api/archived')
@tool_access_required('cutouts')
def get_archived():
    conn  = get_db()
    rows  = conn.execute("SELECT * FROM pending_reviews WHERE status IN ('approved','denied') ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify({'items': [dict(r) for r in rows]})


@cutouts_bp.route('/api/preview/<review_id>')
@tool_access_required('cutouts')
def preview_image(review_id):
    jpg_path = os.path.join(PENDING_DIR, f'{review_id}.jpg')
    if not os.path.exists(jpg_path):
        return 'Not found', 404
    return send_from_directory(PENDING_DIR, f'{review_id}.jpg', mimetype='image/jpeg')


@cutouts_bp.route('/api/pdf/<pdf_id>')
@tool_access_required('cutouts')
def preview_pdf(pdf_id):
    pdf_path = os.path.join(PENDING_DIR, f'{pdf_id}.pdf')
    if not os.path.exists(pdf_path):
        return 'Not found', 404
    return send_from_directory(PENDING_DIR, f'{pdf_id}.pdf', mimetype='application/pdf')


@cutouts_bp.route('/api/approve/<review_id>', methods=['POST'])
@tool_access_required('cutouts')
def approve(review_id):
    conn = get_db()
    row  = conn.execute('SELECT * FROM pending_reviews WHERE id = ? AND status = ?', (review_id, 'pending')).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    jpg_path = os.path.join(PENDING_DIR, f'{review_id}.jpg')
    if not os.path.exists(jpg_path):
        conn.close()
        return jsonify({'error': 'Image missing'}), 404
    result = upload_to_scaleflex(jpg_path, row['jpg_filename'])
    if result['success']:
        conn.execute('UPDATE pending_reviews SET status = ?, scaleflex_url = ? WHERE id = ?', ('approved', result['cdn_url'], review_id))
        conn.commit()
        os.remove(jpg_path)
        cleanup_pdf(conn, row['pdf_id'])
        conn.close()
        return jsonify({'success': True, 'sku': row['sku'], 'filename': row['jpg_filename']})
    conn.close()
    return jsonify({'success': False, 'error': result['error']}), 500


@cutouts_bp.route('/api/deny/<review_id>', methods=['POST'])
@tool_access_required('cutouts')
def deny(review_id):
    conn = get_db()
    row  = conn.execute('SELECT * FROM pending_reviews WHERE id = ? AND status = ?', (review_id, 'pending')).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    jpg_path = os.path.join(PENDING_DIR, f'{review_id}.jpg')
    if os.path.exists(jpg_path):
        os.remove(jpg_path)
    conn.execute('UPDATE pending_reviews SET status = ? WHERE id = ?', ('denied', review_id))
    conn.commit()
    cleanup_pdf(conn, row['pdf_id'])
    conn.close()
    return jsonify({'success': True, 'sku': row['sku']})


@cutouts_bp.route('/api/approve-all', methods=['POST'])
@tool_access_required('cutouts')
def approve_all():
    conn    = get_db()
    rows    = conn.execute('SELECT * FROM pending_reviews WHERE status = ?', ('pending',)).fetchall()
    results = []
    for row in rows:
        jpg_path = os.path.join(PENDING_DIR, f'{row["id"]}.jpg')
        if not os.path.exists(jpg_path):
            results.append({'sku': row['sku'], 'success': False, 'error': 'File missing'})
            continue
        result = upload_to_scaleflex(jpg_path, row['jpg_filename'])
        if result['success']:
            conn.execute('UPDATE pending_reviews SET status = ?, scaleflex_url = ? WHERE id = ?', ('approved', result['cdn_url'], row['id']))
            os.remove(jpg_path)
            results.append({'sku': row['sku'], 'success': True})
        else:
            results.append({'sku': row['sku'], 'success': False, 'error': result['error']})
    conn.commit()
    conn.close()
    return jsonify({'results': results})


@cutouts_bp.route('/api/download-archive')
@tool_access_required('cutouts')
def download_archive():
    asset_filter = request.args.get('type', 'all')
    brand_filter = request.args.get('brand', '')
    date_from    = request.args.get('from', '')
    date_to      = request.args.get('to', '')
    conn         = get_db()
    query        = "SELECT * FROM pending_reviews WHERE status = 'approved'"
    params       = []
    if asset_filter in ('ld', 'co'):
        query += " AND asset_type = ?"
        params.append(asset_filter)
    if brand_filter:
        query += " AND brand = ?"
        params.append(brand_filter)
    if date_from:
        query += " AND created_at >= ?"
        params.append(date_from)
    if date_to:
        query += " AND created_at < ?"
        try:
            to_dt = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            params.append(to_dt.strftime('%Y-%m-%d'))
        except ValueError:
            params.append(date_to)
    query += " ORDER BY brand, sku"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    rows = [r for r in rows if (r['brand'] or 'Unknown').lower() not in ZIP_EXCLUDED_BRANDS]
    if not rows:
        return jsonify({'error': 'No approved items to download'}), 404
    # Return file list for client-side JSZip — files.roxorgroup.com blocks server IPs (Cloudflare 439)
    files = []
    for row in rows:
        brand       = row['brand'] or 'Unknown'
        type_folder = 'Line Drawings' if (row['asset_type'] or 'ld') == 'ld' else 'Cutouts'
        zip_path    = f'{brand}/{type_folder}/{row["jpg_filename"]}'
        url         = row['scaleflex_url'] or f'https://files.roxorgroup.com/{row["jpg_filename"]}'
        files.append({'url': url, 'zip_path': zip_path})
    return jsonify({'files': files})


@cutouts_bp.route('/api/backfill-brands', methods=['POST'])
@tool_access_required('cutouts')
def backfill_brands():
    conn  = get_db()
    rows  = conn.execute("SELECT id, sku FROM pending_reviews WHERE brand IS NULL OR brand = '' OR brand = 'Unknown'").fetchall()
    if not rows:
        conn.close()
        return jsonify({'message': 'Nothing to backfill', 'updated': 0})
    updated = 0
    cache   = {}
    for row in rows:
        sku   = row['sku']
        brand = cache.get(sku) or akeneo_product_info(sku).get('brand', 'Unknown')
        cache[sku] = brand
        if brand and brand != 'Unknown':
            conn.execute('UPDATE pending_reviews SET brand = ? WHERE id = ?', (brand, row['id']))
            updated += 1
    conn.commit()
    conn.close()
    return jsonify({'message': f'Backfilled {updated}/{len(rows)} records', 'updated': updated})
