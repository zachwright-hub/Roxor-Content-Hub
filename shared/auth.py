import sqlite3
import os
from functools import wraps
from datetime import timedelta
from flask import session, redirect, url_for, request, g

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'hub.db')

TOOLS = ['linedrawings', 'cutouts', 'briefs', 'content_tracker', 'content_briefs']


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            email TEXT,
            role TEXT NOT NULL DEFAULT 'user',
            status TEXT NOT NULL DEFAULT 'active',
            access_linedrawings INTEGER NOT NULL DEFAULT 0,
            access_cutouts INTEGER NOT NULL DEFAULT 0,
            access_briefs INTEGER NOT NULL DEFAULT 0,
            access_content_tracker INTEGER NOT NULL DEFAULT 0,
            access_content_briefs INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            last_login TEXT
        );

        CREATE TABLE IF NOT EXISTS invitations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            access_linedrawings INTEGER NOT NULL DEFAULT 0,
            access_cutouts INTEGER NOT NULL DEFAULT 0,
            access_briefs INTEGER NOT NULL DEFAULT 0,
            access_content_tracker INTEGER NOT NULL DEFAULT 0,
            access_content_briefs INTEGER NOT NULL DEFAULT 0,
            invited_by INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT NOT NULL,
            used_at TEXT
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT DEFAULT '',
            link TEXT,
            read_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT (datetime('now')),
            user_id INTEGER,
            username TEXT,
            action TEXT,
            detail TEXT,
            ip_address TEXT
        );
    ''')
    conn.commit()

    existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
    migrations = [
        ('access_content_briefs', "ALTER TABLE users ADD COLUMN access_content_briefs INTEGER NOT NULL DEFAULT 0"),
        ('status',                "ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"),
        ('notify_admin',          "ALTER TABLE users ADD COLUMN notify_admin INTEGER NOT NULL DEFAULT 0"),
    ]
    for col, sql in migrations:
        if col not in existing_cols:
            conn.execute(sql)
    conn.commit()

    existing = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    if existing == 0:
        briefs_db = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'lifestyle operations', 'website', 'data', 'briefs.db'
        )
        seeded = False
        if os.path.exists(briefs_db):
            try:
                src = sqlite3.connect(briefs_db)
                rows = src.execute(
                    "SELECT username, password_hash, display_name, role, is_admin FROM users"
                ).fetchall()
                src.close()
                for row in rows:
                    username, pw_hash, display_name, role, is_admin = row
                    hub_role = 'admin' if (role in ('superadmin', 'admin') or is_admin) else 'user'
                    conn.execute(
                        '''INSERT OR IGNORE INTO users
                           (username, password_hash, display_name, role, status,
                            access_linedrawings, access_cutouts, access_briefs,
                            access_content_tracker, access_content_briefs)
                           VALUES (?, ?, ?, ?, 'active', 1, 1, 1, 1, 1)''',
                        (username, pw_hash, display_name, hub_role)
                    )
                if rows:
                    conn.commit()
                    seeded = True
            except Exception:
                pass
        if not seeded:
            from werkzeug.security import generate_password_hash
            conn.execute(
                '''INSERT INTO users (username, password_hash, display_name, role, status,
                   access_linedrawings, access_cutouts, access_briefs,
                   access_content_tracker, access_content_briefs)
                   VALUES ('admin', ?, 'Administrator', 'admin', 'active', 1, 1, 1, 1, 1)''',
                (generate_password_hash('changeme'),)
            )
            conn.commit()
    conn.close()


def get_current_user():
    if 'user_id' not in session:
        return None
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()
    return user


ROLE_RANK = {'user': 0, 'admin': 1, 'chairman_mao': 2}


def role_rank(role):
    return ROLE_RANK.get(role, 0)


def is_superuser(user):
    return user and user['role'] == 'chairman_mao'


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user or user['status'] != 'active':
            session.clear()
            return redirect(url_for('auth.login', next=request.path))
        g.user = user
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Passes for admin and chairman_mao."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user or user['status'] != 'active' or user['role'] not in ('admin', 'chairman_mao'):
            session.clear()
            return redirect(url_for('auth.login'))
        g.user = user
        return f(*args, **kwargs)
    return decorated


def chairman_mao_required(f):
    """Passes only for chairman_mao."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user or user['status'] != 'active' or user['role'] != 'chairman_mao':
            return redirect(url_for('dashboard.index'))
        g.user = user
        return f(*args, **kwargs)
    return decorated


def tool_access_required(tool_name):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = get_current_user()
            if not user or user['status'] != 'active':
                session.clear()
                return redirect(url_for('auth.login', next=request.path))
            if user['role'] not in ('admin', 'chairman_mao') and not user[f'access_{tool_name}']:
                return redirect(url_for('dashboard.index'))
            g.user = user
            return f(*args, **kwargs)
        return decorated
    return decorator
