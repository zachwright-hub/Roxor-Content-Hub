from shared.auth import get_db


def send_notification(user_id, ntype, title, message='', link=None):
    """Send a notification to a specific user."""
    conn = get_db()
    conn.execute(
        'INSERT INTO notifications (user_id, type, title, message, link) VALUES (?, ?, ?, ?, ?)',
        (user_id, ntype, title, message or '', link)
    )
    conn.commit()
    conn.close()


def send_to_admins(ntype, title, message='', link=None, exclude_user_id=None):
    """Send a notification to all users with notify_admin=1."""
    conn = get_db()
    recipients = conn.execute(
        "SELECT id FROM users WHERE notify_admin = 1 AND status = 'active'"
    ).fetchall()
    for r in recipients:
        if exclude_user_id and r['id'] == exclude_user_id:
            continue
        conn.execute(
            'INSERT INTO notifications (user_id, type, title, message, link) VALUES (?, ?, ?, ?, ?)',
            (r['id'], ntype, title, message or '', link)
        )
    conn.commit()
    conn.close()


def get_unread_count(user_id):
    conn = get_db()
    count = conn.execute(
        'SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL',
        (user_id,)
    ).fetchone()[0]
    conn.close()
    return count


def get_notifications(user_id, limit=40):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT ?',
        (user_id, limit)
    ).fetchall()
    conn.close()
    return rows


def mark_all_read(user_id):
    conn = get_db()
    conn.execute(
        "UPDATE notifications SET read_at = datetime('now') WHERE user_id = ? AND read_at IS NULL",
        (user_id,)
    )
    conn.commit()
    conn.close()
