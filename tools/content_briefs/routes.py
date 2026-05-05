import os
import io
import json
import zipfile
import shutil
import sqlite3
from datetime import datetime, timedelta

from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file, g

from tools.content_briefs import content_briefs_bp
from shared.auth import tool_access_required, get_current_user, DB_PATH as HUB_DB_PATH
from tools.content_briefs.services.akeneo import AkeneoClient
from tools.content_briefs.services.excel import generate_content_brief

# ── Config ────────────────────────────────────────────────────────────────────

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, 'data')
DB_PATH    = os.path.join(DATA_DIR, 'content_briefs.db')
OUTPUT_DIR = os.path.join(BASE_DIR, 'briefs_output')

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

AKENEO_CONFIG = {
    'base_url':      os.environ.get('AKENEO_URL', ''),
    'client_id':     os.environ.get('AKENEO_CLIENT_ID', ''),
    'client_secret': os.environ.get('AKENEO_CLIENT_SECRET', ''),
    'username':      os.environ.get('AKENEO_USERNAME', ''),
    'password':      os.environ.get('AKENEO_PASSWORD', ''),
}

akeneo_client = AkeneoClient(AKENEO_CONFIG)
_attr_cache   = {'data': None, 'loaded_at': None}
_CACHE_TTL    = 3600  # seconds

# ── DB ────────────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS content_briefs (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER NOT NULL,
        name         TEXT NOT NULL,
        sku_count    INTEGER DEFAULT 0,
        status       TEXT DEFAULT 'pending',
        priority     TEXT DEFAULT 'normal',
        assigned_to  INTEGER,
        deadline     TEXT,
        output_path  TEXT,
        downloaded_at TEXT,
        downloaded_by INTEGER,
        completed_at TEXT,
        scoped_attrs TEXT DEFAULT '{}',
        locale_attrs TEXT DEFAULT '{}',
        extra_attrs     TEXT DEFAULT '[]',
        reference_attrs TEXT DEFAULT '[]',
        notes           TEXT,
        sku_list     TEXT,
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    existing = [r[1] for r in conn.execute("PRAGMA table_info(content_briefs)").fetchall()]
    if 'reference_attrs' not in existing:
        conn.execute("ALTER TABLE content_briefs ADD COLUMN reference_attrs TEXT DEFAULT '[]'")
        conn.commit()
    conn.close()


init_db()

# ── Helpers ───────────────────────────────────────────────────────────────────

def is_admin():
    user = g.get('user') or get_current_user()
    return user and user['role'] == 'admin'


def get_hub_users():
    """Users with content_briefs access, for assignment dropdowns."""
    conn = sqlite3.connect(HUB_DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, display_name, username FROM users "
        "WHERE access_content_briefs = 1 AND status = 'active' ORDER BY display_name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _parse_attr_lines(text):
    """Parse "key: attr1, attr2" lines into {"key": ["attr1", "attr2"]}."""
    result = {}
    for line in text.strip().splitlines():
        line = line.strip()
        if ':' not in line:
            continue
        key, _, attrs_raw = line.partition(':')
        key   = key.strip()
        attrs = [a.strip() for a in attrs_raw.replace(';', ',').split(',') if a.strip()]
        if key and attrs:
            result[key] = attrs
    return result


# ── Dashboard ─────────────────────────────────────────────────────────────────

@content_briefs_bp.route('/')
@tool_access_required('content_briefs')
def index():
    db   = get_db()
    user = g.user
    if user['role'] == 'admin':
        briefs = db.execute('''
            SELECT * FROM content_briefs ORDER BY
            CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2
                          WHEN 'normal' THEN 3 WHEN 'low' THEN 4 END,
            created_at DESC
        ''').fetchall()
    else:
        briefs = db.execute(
            'SELECT * FROM content_briefs WHERE user_id = ? ORDER BY created_at DESC',
            (user['id'],)
        ).fetchall()
    db.close()

    today       = datetime.now().strftime('%Y-%m-%d')
    soon        = (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d')
    new_briefs  = [b for b in briefs if b['status'] in (None, 'pending', 'assigned')]
    in_progress = [b for b in briefs if b['status'] == 'in_progress']
    complete    = [b for b in briefs if b['status'] == 'complete']

    users     = get_hub_users()
    users_by_id = {u['id']: u['display_name'] for u in users}
    return render_template('content_briefs/index.html',
                           new_briefs=new_briefs, in_progress=in_progress, complete=complete,
                           today=today, soon=soon,
                           users=users, users_by_id=users_by_id)


# ── Generate ──────────────────────────────────────────────────────────────────

@content_briefs_bp.route('/generate', methods=['GET', 'POST'])
@tool_access_required('content_briefs')
def generate():
    if request.method == 'POST':
        name         = request.form.get('name', '').strip()
        sku_list_raw = request.form.get('sku_list', '')

        if 'sku_file' in request.files:
            f = request.files['sku_file']
            if f and f.filename:
                try:
                    sku_list_raw = f.read().decode('utf-8')
                except UnicodeDecodeError:
                    flash('SKU file must be UTF-8 encoded', 'error')
                    return render_template('content_briefs/generate.html')

        skus = list(dict.fromkeys([s.strip() for s in sku_list_raw.replace('\r', '').split('\n') if s.strip()]))

        if not name:
            flash('Please enter a brief name', 'error')
            return render_template('content_briefs/generate.html')
        if not skus:
            flash('Please enter at least one SKU', 'error')
            return render_template('content_briefs/generate.html')

        try:
            scoped_attrs = json.loads(request.form.get('scoped_attrs_json', '{}') or '{}')
        except (json.JSONDecodeError, TypeError):
            scoped_attrs = {}
        try:
            locale_attrs = json.loads(request.form.get('locale_attrs_json', '{}') or '{}')
        except (json.JSONDecodeError, TypeError):
            locale_attrs = {}
        try:
            extra_attrs = json.loads(request.form.get('extra_attrs_json', '[]') or '[]')
        except (json.JSONDecodeError, TypeError):
            extra_attrs = []
        try:
            reference_attrs = json.loads(request.form.get('reference_attrs_json', '[]') or '[]')
        except (json.JSONDecodeError, TypeError):
            reference_attrs = []

        if not scoped_attrs and not locale_attrs and not extra_attrs:
            flash('Please select at least one attribute to write', 'error')
            return render_template('content_briefs/generate.html')

        session['pending_content_brief'] = {
            'name':            name,
            'skus':            skus,
            'scoped_attrs':    scoped_attrs,
            'locale_attrs':    locale_attrs,
            'extra_attrs':     extra_attrs,
            'reference_attrs': reference_attrs,
            'deadline':        request.form.get('deadline', '').strip() or None,
            'notes':           request.form.get('notes', '').strip() or None,
        }
        return redirect(url_for('content_briefs.processing'))

    return render_template('content_briefs/generate.html')


@content_briefs_bp.route('/processing')
@tool_access_required('content_briefs')
def processing():
    if 'pending_content_brief' not in session:
        return redirect(url_for('content_briefs.generate'))
    pb = session['pending_content_brief']
    return render_template('content_briefs/processing.html',
                           brief_name=pb['name'], sku_count=len(pb['skus']))


@content_briefs_bp.route('/api/process', methods=['POST'])
@tool_access_required('content_briefs')
def api_process():
    if 'pending_content_brief' not in session:
        return jsonify({'error': 'No pending brief'}), 400

    try:
        pb           = session['pending_content_brief']
        name         = pb['name']
        skus         = pb['skus']
        scoped_attrs = pb['scoped_attrs']
        locale_attrs = pb['locale_attrs']
        extra_attrs     = pb['extra_attrs']
        reference_attrs = pb.get('reference_attrs', [])
        deadline        = pb.get('deadline')
        notes        = pb.get('notes')

        timestamp     = datetime.now().strftime('%Y-%m-%d_%H%M%S')
        output_folder = os.path.join(OUTPUT_DIR, f'{name}_{timestamp}')
        os.makedirs(output_folder, exist_ok=True)

        products   = akeneo_client.get_products(skus)
        brief_rows = [
            akeneo_client.get_product_values(products.get(sku), sku, scoped_attrs, locale_attrs, extra_attrs, reference_attrs)
            for sku in skus
        ]
        not_found = [r['sku'] for r in brief_rows if not r['found']]

        excel_path = os.path.join(output_folder, f'{name}.xlsx')
        generate_content_brief(brief_rows, excel_path, scoped_attrs, locale_attrs, extra_attrs,
                               brief_name=name, notes=notes, reference_attrs=reference_attrs)

        db     = get_db()
        cursor = db.execute(
            '''INSERT INTO content_briefs
               (user_id, name, sku_count, status, deadline, output_path,
                scoped_attrs, locale_attrs, extra_attrs, reference_attrs, notes, sku_list)
               VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)''',
            (g.user['id'], name, len(brief_rows), deadline, output_folder,
             json.dumps(scoped_attrs), json.dumps(locale_attrs), json.dumps(extra_attrs),
             json.dumps(reference_attrs), notes, json.dumps(skus))
        )
        db.commit()
        brief_id = cursor.lastrowid
        db.close()

        session.pop('pending_content_brief', None)
        return jsonify({'success': True, 'brief_id': brief_id, 'name': name,
                        'sku_count': len(brief_rows), 'not_found': not_found})

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ── Brief Management ──────────────────────────────────────────────────────────

@content_briefs_bp.route('/view/<int:brief_id>')
@tool_access_required('content_briefs')
def view_brief(brief_id):
    db    = get_db()
    brief = db.execute('SELECT * FROM content_briefs WHERE id = ?', (brief_id,)).fetchone()
    db.close()
    if not brief:
        flash('Brief not found', 'error')
        return redirect(url_for('content_briefs.index'))
    return render_template('content_briefs/view_brief.html',
                           brief=brief,
                           scoped_attrs=json.loads(brief['scoped_attrs'] or '{}'),
                           locale_attrs=json.loads(brief['locale_attrs'] or '{}'),
                           extra_attrs=json.loads(brief['extra_attrs'] or '[]'),
                           reference_attrs=json.loads(brief['reference_attrs'] or '[]'),
                           sku_list=json.loads(brief['sku_list'] or '[]'),
                           users=get_hub_users())


@content_briefs_bp.route('/download/<int:brief_id>')
@tool_access_required('content_briefs')
def download(brief_id):
    db   = get_db()
    user = g.user
    if user['role'] == 'admin':
        brief = db.execute('SELECT * FROM content_briefs WHERE id = ?', (brief_id,)).fetchone()
    else:
        brief = db.execute('SELECT * FROM content_briefs WHERE id = ? AND user_id = ?',
                           (brief_id, user['id'])).fetchone()

    if not brief or not brief['output_path'] or not os.path.exists(brief['output_path']):
        db.close()
        flash('Files not found', 'error')
        return redirect(url_for('content_briefs.index'))

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    if brief['status'] in (None, 'pending', 'assigned'):
        db.execute('UPDATE content_briefs SET downloaded_at=?, downloaded_by=?, status=? WHERE id=?',
                   (now_str, user['id'], 'in_progress', brief_id))
    else:
        db.execute('UPDATE content_briefs SET downloaded_at=?, downloaded_by=? WHERE id=?',
                   (now_str, user['id'], brief_id))
    db.commit()
    db.close()

    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(brief['output_path']):
            for file in files:
                fp = os.path.join(root, file)
                zf.write(fp, os.path.relpath(fp, brief['output_path']))
    mem.seek(0)
    return send_file(mem, mimetype='application/zip', as_attachment=True,
                     download_name=f"{brief['name']}_content_brief.zip")


@content_briefs_bp.route('/delete/<int:brief_id>', methods=['POST'])
@tool_access_required('content_briefs')
def delete_brief(brief_id):
    if not is_admin():
        flash('Admin only', 'error')
        return redirect(url_for('content_briefs.index'))
    db    = get_db()
    brief = db.execute('SELECT * FROM content_briefs WHERE id = ?', (brief_id,)).fetchone()
    if brief:
        if brief['output_path'] and os.path.exists(brief['output_path']):
            shutil.rmtree(brief['output_path'], ignore_errors=True)
        db.execute('DELETE FROM content_briefs WHERE id = ?', (brief_id,))
        db.commit()
        flash('Brief deleted', 'success')
    db.close()
    return redirect(url_for('content_briefs.index'))


@content_briefs_bp.route('/update-status/<int:brief_id>', methods=['POST'])
@tool_access_required('content_briefs')
def update_status(brief_id):
    new_status = request.form.get('status')
    if new_status not in ['pending', 'assigned', 'in_progress', 'complete']:
        flash('Invalid status', 'error')
        return redirect(url_for('content_briefs.index'))
    db = get_db()
    brief = db.execute('SELECT name FROM content_briefs WHERE id = ?', (brief_id,)).fetchone()
    db.execute('UPDATE content_briefs SET status=? WHERE id=?', (new_status, brief_id))
    if new_status == 'complete':
        db.execute("UPDATE content_briefs SET completed_at=? WHERE id=? AND completed_at IS NULL",
                   (datetime.now().strftime('%Y-%m-%d %H:%M'), brief_id))
    db.commit()
    db.close()
    if new_status == 'complete' and brief:
        try:
            from shared.notifications import send_to_admins
            send_to_admins(
                ntype='brief_complete',
                title=f'Brief complete: {brief["name"]}',
                message='A content brief has been marked complete.',
                link='/content-briefs'
            )
        except Exception:
            pass
    flash('Status updated', 'success')
    return redirect(request.referrer or url_for('content_briefs.index'))


@content_briefs_bp.route('/update-priority/<int:brief_id>', methods=['POST'])
@tool_access_required('content_briefs')
def update_priority(brief_id):
    if not is_admin():
        flash('Admin only', 'error')
        return redirect(url_for('content_briefs.index'))
    new_priority = request.form.get('priority')
    if new_priority not in ['low', 'normal', 'high', 'urgent']:
        flash('Invalid priority', 'error')
        return redirect(url_for('content_briefs.index'))
    db = get_db()
    db.execute('UPDATE content_briefs SET priority=? WHERE id=?', (new_priority, brief_id))
    db.commit()
    db.close()
    flash('Priority updated', 'success')
    return redirect(request.referrer or url_for('content_briefs.index'))


@content_briefs_bp.route('/assign/<int:brief_id>', methods=['POST'])
@tool_access_required('content_briefs')
def assign_brief(brief_id):
    if not is_admin():
        flash('Admin only', 'error')
        return redirect(url_for('content_briefs.index'))
    assigned_to = request.form.get('assigned_to') or None
    if assigned_to:
        assigned_to = int(assigned_to)
    db = get_db()
    brief = db.execute('SELECT * FROM content_briefs WHERE id = ?', (brief_id,)).fetchone()
    if brief:
        new_status = 'assigned' if assigned_to else 'pending'
        db.execute('UPDATE content_briefs SET assigned_to=?, status=? WHERE id=?',
                   (assigned_to, new_status, brief_id))
        db.commit()
        if assigned_to:
            try:
                from shared.notifications import send_notification
                send_notification(
                    assigned_to, 'brief_assigned',
                    f'Brief assigned: {brief["name"]}',
                    message=f'You have been assigned a new content brief ({brief.get("sku_count", "?")} SKUs).',
                    link='/content-briefs'
                )
            except Exception:
                pass
        flash('Brief assigned', 'success')
    db.close()
    return redirect(request.referrer or url_for('content_briefs.index'))


@content_briefs_bp.route('/api/briefs/<int:brief_id>/deadline', methods=['POST'])
@tool_access_required('content_briefs')
def update_deadline(brief_id):
    if not is_admin():
        return jsonify({'error': 'Admin only'}), 403
    data     = request.get_json() or {}
    deadline = data.get('deadline', '').strip() or None
    db       = get_db()
    db.execute('UPDATE content_briefs SET deadline=? WHERE id=?', (deadline, brief_id))
    db.commit()
    db.close()
    return jsonify({'success': True})


# ── Akeneo Metadata APIs (used by generate form dropdowns) ────────────────────

@content_briefs_bp.route('/api/attributes')
@tool_access_required('content_briefs')
def api_attributes():
    global _attr_cache
    now = datetime.now()
    if (_attr_cache['data'] and _attr_cache['loaded_at'] and
            (now - _attr_cache['loaded_at']).seconds < _CACHE_TTL):
        return jsonify(_attr_cache['data'])

    if not AKENEO_CONFIG.get('base_url'):
        return jsonify({'error': 'Akeneo not configured'}), 503

    try:
        result = {
            'attributes': akeneo_client.get_all_attributes(),
            'channels':   akeneo_client.get_channels(),
            'locales':    akeneo_client.get_active_locales(),
        }
        _attr_cache = {'data': result, 'loaded_at': now}
        return jsonify(result)
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@content_briefs_bp.route('/api/attributes/refresh', methods=['POST'])
@tool_access_required('content_briefs')
def api_attributes_refresh():
    global _attr_cache
    _attr_cache = {'data': None, 'loaded_at': None}
    return jsonify({'success': True})
