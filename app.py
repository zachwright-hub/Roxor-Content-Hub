from dotenv import load_dotenv
load_dotenv()

from flask import Flask, g
from datetime import timedelta
import os

from shared.auth import init_db, get_current_user
from blueprints.auth import auth_bp
from blueprints.dashboard import dashboard_bp
from blueprints.notifications import notifications_bp
from tools.linedrawings import linedrawings_bp
from tools.cutouts import cutouts_bp
from tools.briefs import briefs_bp
from tools.content_tracker import content_tracker_bp
from tools.content_briefs import content_briefs_bp

app = Flask(__name__, template_folder='UI/templates', static_folder='UI/static')
app.secret_key = os.environ['SESSION_SECRET']
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=False,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)

app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(notifications_bp)
app.register_blueprint(linedrawings_bp,      url_prefix='/linedrawings')
app.register_blueprint(cutouts_bp,           url_prefix='/cutouts')
app.register_blueprint(briefs_bp,            url_prefix='/briefs')
app.register_blueprint(content_tracker_bp,  url_prefix='/content-tracker')
app.register_blueprint(content_briefs_bp,   url_prefix='/content-briefs')


@app.context_processor
def inject_user():
    user   = get_current_user()
    unread = 0
    if user:
        try:
            from shared.notifications import get_unread_count
            unread = get_unread_count(user['id'])
        except Exception:
            pass
    return {'current_user': user, 'unread_notifications': unread}


if __name__ == '__main__':
    init_db()
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        from tools.content_tracker.services.scheduler import start_scheduler
        start_scheduler()
    app.run(debug=True, port=5005)
