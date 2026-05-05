from flask import Blueprint, render_template
from shared.auth import tool_access_required

linedrawings_bp = Blueprint(
    'linedrawings', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/linedrawings/static',
)


@linedrawings_bp.route('/')
@tool_access_required('linedrawings')
def index():
    return render_template('linedrawings/coming_soon.html', tool_name='Line Drawing Generator')
