from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from werkzeug.security import check_password_hash
from shared.auth import get_db, get_current_user

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if get_current_user():
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        conn = get_db()
        # Match by email, with username fallback for accounts that predate email login
        user = conn.execute(
            'SELECT * FROM users WHERE LOWER(email) = ? OR (email IS NULL AND username = ?)',
            (email, email)
        ).fetchone()
        conn.close()

        if user and user['status'] == 'active' and check_password_hash(user['password_hash'], password):
            session.permanent = True
            session['user_id'] = user['id']
            conn = get_db()
            conn.execute("UPDATE users SET last_login = datetime('now') WHERE id = ?", (user['id'],))
            conn.execute(
                "INSERT INTO audit_log (user_id, username, action, ip_address) VALUES (?, ?, 'login', ?)",
                (user['id'], user['username'], request.remote_addr)
            )
            conn.commit()
            conn.close()
            return redirect(request.args.get('next') or url_for('dashboard.index'))

        flash('Invalid email or password.', 'error')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
def logout():
    user = get_current_user()
    if user:
        conn = get_db()
        conn.execute(
            "INSERT INTO audit_log (user_id, username, action, ip_address) VALUES (?, ?, 'logout', ?)",
            (user['id'], user['username'], request.remote_addr)
        )
        conn.commit()
        conn.close()
    session.clear()
    return redirect(url_for('auth.login'))
