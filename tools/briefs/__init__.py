from flask import Blueprint

briefs_bp = Blueprint(
    'briefs', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/briefs/static',
)

from tools.briefs import routes  # noqa: F401, E402
