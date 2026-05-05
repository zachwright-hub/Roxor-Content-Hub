from flask import Blueprint

content_tracker_bp = Blueprint(
    'content_tracker', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/content-tracker/static',
)

from tools.content_tracker import routes  # noqa: F401, E402
