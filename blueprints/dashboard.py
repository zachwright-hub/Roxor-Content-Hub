import os
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from werkzeug.security import generate_password_hash

from shared.auth import (login_required, admin_required, chairman_mao_required,
                         get_current_user, get_db, TOOLS, role_rank, is_superuser)

dashboard_bp = Blueprint('dashboard', __name__)

ROLE_LABELS = {
    'user':         'User',
    'admin':        'Admin',
    'chairman_mao': 'Chairman Mao',
}

TOOL_META = {
    'linedrawings':    {'label': 'Line Drawing Generator'},
    'cutouts':         {'label': 'LD & Cutout Uploader'},
    'briefs':          {'label': 'Lifestyle Brief Generator'},
    'content_tracker': {'label': 'Roxor Content Tracker'},
    'content_briefs':  {'label': 'Content Brief Generator'},
}


# ── Dashboard ──────────────────────────────────────────────────────────────────

@dashboard_bp.route('/')
@login_required
def index():
    user = get_current_user()
    conn = get_db()
    user_count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    conn.close()

    tools = [
        {
            'id':          'linedrawings',
            'name':        'Line Drawing Generator',
            'description': 'Generate AI line drawings for products, batch process SKUs, approve and push to Scaleflex.',
            'url':         '/linedrawings',
            'status':      'active',
            'access_key':  'access_linedrawings',
        },
        {
            'id':          'cutouts',
            'name':        'LD & Cutout Uploader',
            'description': 'Upload line drawings (PDF→JPG) and cutouts (JPG), review side-by-side against Akeneo, approve to push to Scaleflex.',
            'url':         '/cutouts',
            'status':      'active',
            'access_key':  'access_cutouts',
        },
        {
            'id':          'briefs',
            'name':        'Lifestyle Brief Generator',
            'description': 'Create and manage lifestyle photography briefs, assign to photographers, track progress.',
            'url':         '/briefs',
            'status':      'active',
            'access_key':  'access_briefs',
        },
        {
            'id':          'content_tracker',
            'name':        'Imagery Tracker',
            'description': 'Monitor asset family coverage (cutouts, lifestyles, line drawings) across all Roxor brands.',
            'url':         '/content-tracker/imagery',
            'icon':        'camera',
            'status':      'active',
            'access_key':  'access_content_tracker',
        },
        {
            'id':          'content_tracker',
            'name':        'Content Tracker',
            'description': 'Track attribute and copy completeness by scope and marketplace across all Roxor brands.',
            'url':         '/content-tracker/content',
            'icon':        'chart-bar',
            'status':      'active',
            'access_key':  'access_content_tracker',
        },
        {
            'id':          'content_briefs',
            'name':        'Content Brief Generator',
            'description': 'Package SKUs with Akeneo attribute data into Excel briefs for copywriters.',
            'url':         '/content-briefs',
            'status':      'active',
            'access_key':  'access_content_briefs',
        },
    ]

    accessible = [t for t in tools
                  if user['role'] in ('admin', 'chairman_mao') or user[t['access_key']]]
    return render_template('dashboard.html', tools=accessible, user=user, user_count=user_count)


# ── Admin: user list ───────────────────────────────────────────────────────────

@dashboard_bp.route('/admin/users')
@admin_required
def users():
    user = get_current_user()
    conn = get_db()
    all_users = conn.execute('SELECT * FROM users ORDER BY created_at DESC').fetchall()
    pending_invites = conn.execute(
        "SELECT * FROM invitations WHERE used_at IS NULL AND expires_at > datetime('now') ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return render_template('admin/users.html',
                           users=all_users,
                           pending_invites=pending_invites,
                           user=user,
                           tools=TOOLS,
                           tool_meta=TOOL_META,
                           role_labels=ROLE_LABELS)


# ── Admin: invite user ─────────────────────────────────────────────────────────

@dashboard_bp.route('/admin/invite', methods=['GET', 'POST'])
@admin_required
def invite_user():
    user = get_current_user()

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        role  = request.form.get('role', 'user')
        access = {t: 1 if request.form.get(f'access_{t}') else 0 for t in TOOLS}

        # Only chairman_mao can create admin or chairman_mao accounts
        if role_rank(role) >= role_rank('admin') and not is_superuser(user):
            role = 'user'

        if not email:
            flash('Email address is required.', 'error')
            return render_template('admin/invite.html', user=user, tools=TOOLS,
                                   tool_meta=TOOL_META, role_labels=ROLE_LABELS)

        token      = secrets.token_urlsafe(32)
        expires_at = (datetime.utcnow() + timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')

        conn = get_db()
        conn.execute(
            '''INSERT INTO invitations
               (token, email, role, access_linedrawings, access_cutouts, access_briefs,
                access_content_tracker, access_content_briefs, invited_by, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (token, email, role,
             access['linedrawings'], access['cutouts'], access['briefs'],
             access['content_tracker'], access['content_briefs'],
             user['id'], expires_at)
        )
        conn.execute(
            "INSERT INTO audit_log (user_id, username, action, detail, ip_address) VALUES (?, ?, 'invite_sent', ?, ?)",
            (user['id'], user['username'], email, request.remote_addr)
        )
        conn.commit()
        conn.close()

        base_url  = os.environ.get('APP_BASE_URL', 'http://localhost:5005').rstrip('/')
        setup_url = f"{base_url}/setup/{token}"

        try:
            from shared.email import send_invite
            send_invite(email, setup_url, user['display_name'])
            flash(f'Invite sent to {email}.', 'success')
        except Exception as e:
            flash(f'Invite created but email failed ({e}). Share this link manually: {setup_url}', 'info')

        return redirect(url_for('dashboard.users'))

    return render_template('admin/invite.html', user=user, tools=TOOLS,
                           tool_meta=TOOL_META, role_labels=ROLE_LABELS)


# ── Public: account setup via invite token ─────────────────────────────────────

@dashboard_bp.route('/setup/<token>', methods=['GET', 'POST'])
def setup_account(token):
    conn = get_db()
    invite = conn.execute(
        "SELECT * FROM invitations WHERE token = ? AND used_at IS NULL AND expires_at > datetime('now')",
        (token,)
    ).fetchone()

    if not invite:
        conn.close()
        return render_template('admin/setup.html',
                               error='This invite link is invalid or has expired.',
                               token=None)

    if request.method == 'POST':
        display_name     = request.form.get('display_name', '').strip()
        password         = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        errors = []
        if not display_name:              errors.append('Name is required.')
        if len(password) < 8:            errors.append('Password must be at least 8 characters.')
        if password != confirm_password: errors.append('Passwords do not match.')

        if errors:
            conn.close()
            return render_template('admin/setup.html',
                                   invite=invite, token=token, errors=errors,
                                   display_name=display_name,
                                   tools=TOOLS, tool_meta=TOOL_META, role_labels=ROLE_LABELS)

        # Derive a unique internal username from the email address
        import re
        base = re.sub(r'[^a-z0-9.]', '.', invite['email'].split('@')[0].lower()).strip('.')
        username = base
        suffix   = 2
        while conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone():
            username = f'{base}{suffix}'
            suffix  += 1

        pw_hash = generate_password_hash(password)
        conn.execute(
            '''INSERT INTO users
               (username, password_hash, display_name, email, role, status,
                access_linedrawings, access_cutouts, access_briefs,
                access_content_tracker, access_content_briefs)
               VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)''',
            (username, pw_hash, display_name, invite['email'], invite['role'],
             invite['access_linedrawings'], invite['access_cutouts'],
             invite['access_briefs'], invite['access_content_tracker'],
             invite['access_content_briefs'])
        )
        conn.execute(
            "UPDATE invitations SET used_at = datetime('now') WHERE token = ?", (token,)
        )
        new_user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.execute(
            "INSERT INTO audit_log (user_id, username, action, detail) VALUES (?, ?, 'account_created', 'via invite')",
            (new_user['id'], username)
        )
        conn.commit()
        conn.close()

        session.permanent = True
        session['user_id'] = new_user['id']
        return redirect(url_for('dashboard.index'))

    conn.close()
    return render_template('admin/setup.html', invite=invite, token=token,
                           tools=TOOLS, tool_meta=TOOL_META, role_labels=ROLE_LABELS)


# ── Admin: edit user ───────────────────────────────────────────────────────────

@dashboard_bp.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    current = get_current_user()
    conn    = get_db()
    target  = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

    if not target:
        conn.close()
        return redirect(url_for('dashboard.users'))

    # Regular admins can't edit accounts with equal or higher rank
    if not is_superuser(current) and role_rank(target['role']) >= role_rank('admin'):
        conn.close()
        flash("You don't have permission to edit admin accounts.", 'error')
        return redirect(url_for('dashboard.users'))

    if request.method == 'POST':
        display_name = request.form.get('display_name', '').strip()
        email        = request.form.get('email', '').strip()
        role         = request.form.get('role', 'user')
        access       = {t: 1 if request.form.get(f'access_{t}') else 0 for t in TOOLS}
        notify_admin = 1 if request.form.get('notify_admin') else 0

        # Clamp role to what the current user is allowed to assign
        if not is_superuser(current) and role_rank(role) >= role_rank('admin'):
            role = 'user'

        new_pw = request.form.get('new_password', '').strip()
        pw_clause, pw_vals = '', []
        if new_pw:
            if len(new_pw) < 8:
                conn.close()
                flash('New password must be at least 8 characters.', 'error')
                return render_template('admin/edit_user.html', user=current, target=target,
                                       tools=TOOLS, tool_meta=TOOL_META, role_labels=ROLE_LABELS)
            pw_clause = ', password_hash = ?'
            pw_vals   = [generate_password_hash(new_pw)]

        conn.execute(
            f'''UPDATE users SET display_name=?, email=?, role=?, notify_admin=?,
                access_linedrawings=?, access_cutouts=?, access_briefs=?,
                access_content_tracker=?, access_content_briefs=?
                {pw_clause} WHERE id=?''',
            [display_name, email, role, notify_admin,
             access['linedrawings'], access['cutouts'], access['briefs'],
             access['content_tracker'], access['content_briefs']]
            + pw_vals + [user_id]
        )
        conn.execute(
            "INSERT INTO audit_log (user_id, username, action, detail, ip_address) VALUES (?, ?, 'edit_user', ?, ?)",
            (current['id'], current['username'], f'edited {target["username"]}', request.remote_addr)
        )
        conn.commit()
        conn.close()
        flash(f'{display_name} updated.', 'success')
        return redirect(url_for('dashboard.users'))

    conn.close()
    return render_template('admin/edit_user.html', user=current, target=target,
                           tools=TOOLS, tool_meta=TOOL_META, role_labels=ROLE_LABELS)


# ── Admin: delete user ─────────────────────────────────────────────────────────

@dashboard_bp.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    current = get_current_user()

    if current['id'] == user_id:
        flash("You can't delete your own account.", 'error')
        return redirect(url_for('dashboard.users'))

    conn   = get_db()
    target = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

    if target:
        if not is_superuser(current) and role_rank(target['role']) >= role_rank('admin'):
            conn.close()
            flash("You don't have permission to delete admin accounts.", 'error')
            return redirect(url_for('dashboard.users'))

        if target['role'] in ('admin', 'chairman_mao'):
            count = conn.execute(
                "SELECT COUNT(*) FROM users WHERE role IN ('admin','chairman_mao')"
            ).fetchone()[0]
            if count <= 1:
                conn.close()
                flash("Can't delete the last admin account.", 'error')
                return redirect(url_for('dashboard.users'))

        conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.execute(
            "INSERT INTO audit_log (user_id, username, action, detail, ip_address) VALUES (?, ?, 'delete_user', ?, ?)",
            (current['id'], current['username'], f'deleted {target["username"]}', request.remote_addr)
        )
        conn.commit()
        flash(f'{target["display_name"]} deleted.', 'success')

    conn.close()
    return redirect(url_for('dashboard.users'))


# ── Admin: enable / disable user ───────────────────────────────────────────────

@dashboard_bp.route('/admin/users/<int:user_id>/toggle-status', methods=['POST'])
@admin_required
def toggle_user_status(user_id):
    current = get_current_user()

    if current['id'] == user_id:
        flash("You can't disable your own account.", 'error')
        return redirect(url_for('dashboard.users'))

    conn   = get_db()
    target = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

    if target:
        if not is_superuser(current) and role_rank(target['role']) >= role_rank('admin'):
            conn.close()
            flash("You don't have permission to disable admin accounts.", 'error')
            return redirect(url_for('dashboard.users'))

        if target['status'] == 'active' and target['role'] in ('admin', 'chairman_mao'):
            active_count = conn.execute(
                "SELECT COUNT(*) FROM users WHERE role IN ('admin','chairman_mao') AND status = 'active'"
            ).fetchone()[0]
            if active_count <= 1:
                conn.close()
                flash("Can't disable the last active admin.", 'error')
                return redirect(url_for('dashboard.users'))

        new_status = 'inactive' if target['status'] == 'active' else 'active'
        conn.execute('UPDATE users SET status = ? WHERE id = ?', (new_status, user_id))
        conn.execute(
            "INSERT INTO audit_log (user_id, username, action, detail, ip_address) VALUES (?, ?, ?, ?, ?)",
            (current['id'], current['username'],
             f'set_{new_status}', target['username'], request.remote_addr)
        )
        conn.commit()
        label = 'enabled' if new_status == 'active' else 'disabled'
        flash(f'{target["display_name"]} {label}.', 'success')

    conn.close()
    return redirect(url_for('dashboard.users'))


# ── Admin: revoke pending invite ───────────────────────────────────────────────

@dashboard_bp.route('/admin/invites/<int:invite_id>/revoke', methods=['POST'])
@admin_required
def revoke_invite(invite_id):
    conn = get_db()
    conn.execute(
        "UPDATE invitations SET used_at = 'REVOKED', expires_at = datetime('now') WHERE id = ?",
        (invite_id,)
    )
    conn.commit()
    conn.close()
    flash('Invite revoked.', 'success')
    return redirect(url_for('dashboard.users'))


# ── Chairman Mao: audit log ────────────────────────────────────────────────────

@dashboard_bp.route('/admin/audit-log')
@chairman_mao_required
def audit_log():
    user = get_current_user()
    conn = get_db()
    page     = max(1, request.args.get('page', 1, type=int))
    per_page = 50
    offset   = (page - 1) * per_page

    total = conn.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0]
    rows  = conn.execute(
        'SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ? OFFSET ?',
        (per_page, offset)
    ).fetchall()
    conn.close()

    pages = (total + per_page - 1) // per_page
    return render_template('admin/audit_log.html',
                           user=user,
                           rows=rows,
                           page=page,
                           pages=pages,
                           total=total)


# ── Admin: toggle tool access (quick toggle from table) ────────────────────────

@dashboard_bp.route('/admin/users/<int:user_id>/toggle/<tool>', methods=['POST'])
@admin_required
def toggle_tool_access(user_id, tool):
    current = get_current_user()
    if tool not in TOOLS:
        return redirect(url_for('dashboard.users'))

    conn   = get_db()
    target = conn.execute('SELECT role FROM users WHERE id = ?', (user_id,)).fetchone()

    if target and not is_superuser(current) and role_rank(target['role']) >= role_rank('admin'):
        conn.close()
        flash("You don't have permission to modify admin accounts.", 'error')
        return redirect(url_for('dashboard.users'))

    col = f'access_{tool}'
    row = conn.execute(f'SELECT {col} FROM users WHERE id = ?', (user_id,)).fetchone()
    if row:
        conn.execute(f'UPDATE users SET {col} = ? WHERE id = ?', (0 if row[0] else 1, user_id))
        conn.commit()
    conn.close()
    return redirect(url_for('dashboard.users'))
