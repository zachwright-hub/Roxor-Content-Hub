from flask import Blueprint, render_template, redirect, url_for, request, flash

from shared.auth import login_required, get_current_user
from shared.notifications import get_notifications, mark_all_read, send_to_admins

notifications_bp = Blueprint('notifications', __name__)


@notifications_bp.route('/notifications')
@login_required
def index():
    user          = get_current_user()
    notifications = get_notifications(user['id'])
    mark_all_read(user['id'])
    return render_template('notifications/index.html', user=user, notifications=notifications)


@notifications_bp.route('/notifications/request-batch', methods=['GET', 'POST'])
@login_required
def request_batch():
    user = get_current_user()

    if request.method == 'POST':
        tool    = request.form.get('tool', '').strip()
        message = request.form.get('message', '').strip()

        if not message:
            flash('Please describe what you need.', 'error')
            return render_template('notifications/request_batch.html', user=user)

        link = '/briefs' if tool == 'lifestyle' else '/content-briefs'
        send_to_admins(
            ntype='batch_requested',
            title=f'Batch request — {user["display_name"]}',
            message=f'[{"Lifestyle Briefs" if tool == "lifestyle" else "Content Briefs"}] {message}',
            link=link,
            exclude_user_id=user['id'],
        )
        flash('Request sent to the team.', 'success')
        return redirect(url_for('notifications.request_batch'))

    return render_template('notifications/request_batch.html', user=user)
