from flask import Blueprint

content_briefs_bp = Blueprint(
    'content_briefs', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/content-briefs/static',
)

from tools.content_briefs import routes  # noqa: F401, E402
