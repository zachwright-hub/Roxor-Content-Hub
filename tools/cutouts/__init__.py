from flask import Blueprint

cutouts_bp = Blueprint(
    'cutouts', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/cutouts/static',
)

from tools.cutouts import routes  # noqa: E402, F401
