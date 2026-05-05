"""
Line Drawing Generator — generation logic only.
Imported by tools/linedrawings/routes.py. No CLI, no standalone auth.
"""

import os
import json
import time
import uuid
import re
import requests
import boto3
from botocore.config import Config as BotoConfig

# ── Config ──────────────────────────────────────────────────────────────────

AKENEO_URL = os.getenv('AKENEO_URL')
AKENEO_CLIENT_ID = os.getenv('AKENEO_CLIENT_ID')
AKENEO_CLIENT_SECRET = os.getenv('AKENEO_CLIENT_SECRET')
AKENEO_USERNAME = os.getenv('AKENEO_USERNAME')
AKENEO_PASSWORD = os.getenv('AKENEO_PASSWORD')

KIE_API_KEY = os.getenv('KIE_AI_API_KEY')
KIE_API_URL = os.getenv('KIE_AI_API_URL', 'https://api.kie.ai/api/v1/jobs/createTask')
KIE_POLL_URL = 'https://api.kie.ai/api/v1/jobs/recordInfo'
KIE_MODEL = os.getenv('KIE_AI_MODEL', 'nano-banana-pro')

S3_BUCKET = os.getenv('S3_BUCKET', '')
AWS_REGION = os.getenv('AWS_REGION', 'eu-west-2')

# ── Dimension attributes per category ──────────────────────────────────────

_CORE = [('product_width', 'W'), ('product_height', 'H'), ('product_depth', 'D')]
_CORE_L = [('product_width', 'W'), ('product_height', 'H'), ('product_length', 'L')]
_WLD = [('product_width', 'W'), ('product_length', 'L'), ('product_depth', 'D')]
_WHD = _CORE
_WH = [('product_width', 'W'), ('product_height', 'H')]

_FURNITURE = _CORE
_BASIN = _CORE + [
    ('inner_bowl_width', 'Bowl W'), ('inner_bowl_height', 'Bowl H'), ('inner_bowl_depth', 'Bowl D'),
]
_BATH = [('product_width', 'W'), ('product_height', 'H'), ('product_length', 'L')]
_TRAY = _WLD
_ENCLOSURE = _WH + [('entry_width', 'Entry W')]
_SCREEN = _WH
_TAP = [
    ('tap_spout_height', 'Spout H'), ('tap_spout_projection', 'Spout P'),
    ('product_height', 'H'), ('product_width', 'W'),
]
_VALVE = _WH
_SHOWER_HEAD = [
    ('shower_head_dia', 'Head Ø'), ('product_width', 'W'), ('product_height', 'H'),
]
_SHOWER_ARM = [('product_length', 'L'), ('product_width', 'W')]
_SHOWER_KIT = [('product_height', 'H'), ('hose_length', 'Hose L')]
_RADIATOR = _WH
_TOILET = _CORE
_MIRROR = _CORE
_SINK = _CORE + [
    ('inner_bowl_width', 'Bowl W'), ('inner_bowl_depth', 'Bowl D'),
]
_BATH_SCREEN = _WH + [('swing_in', 'Swing In'), ('swing_out', 'Swing Out')]
_WORKTOP = [('product_width', 'W'), ('product_depth', 'D')]
_DEFAULT = _CORE

CATEGORY_DIMS = {
    # ── Furniture ────────────────────────────────
    'furniture_floorstanding_vanities': _FURNITURE,
    'furniture_wall_hung_vanities': _FURNITURE,
    'furniture_counter_top_vanities': _FURNITURE,
    'vanity_units': _FURNITURE,
    'cloakroom_vanities': _FURNITURE,
    'full_depth_furniture_packs': _FURNITURE,
    'compact_furniture_pack': _FURNITURE,
    'wc_units': _FURNITURE,
    'tall_units': _FURNITURE,
    'fitted_units': _FURNITURE,
    'wall_units': _FURNITURE,
    'furniture_vanity_units': _FURNITURE,
    'floor_standing_vanities': _FURNITURE,
    'furniture': _FURNITURE,
    'furniture_accessories': _FURNITURE,

    # ── Basins ───────────────────────────────────
    'furniture_basins': _BASIN,
    'basin_only': _BASIN,
    'basins_and_full_pedestals': _BASIN,
    'basins_and_semi_pedestals': _BASIN,
    'wall_hung_basins': _BASIN,
    'vessels': _BASIN,
    'basins': _BASIN,
    'pedestal_only': _CORE,

    # ── Baths ────────────────────────────────────
    'freestanding_baths': _BATH,
    'single_ended_baths': _BATH,
    'double_ended_baths': _BATH,
    'back_to_wall_baths': _BATH,
    'corner_baths': _BATH,
    'curved_baths': _BATH,
    'straight_baths': _BATH,
    'whirlpool_baths': _BATH,
    'baths': _BATH,
    'square_shower_baths': _BATH,
    'p_shaped_shower_baths': _BATH,
    'b_shaped_shower_baths': _BATH,
    'shower_baths': _BATH,
    'bath_panels': _WH,

    # ── Shower trays ─────────────────────────────
    'standard_shower_trays': _TRAY,
    'shower_trays': _TRAY,
    'rectangular_trays': _TRAY,
    'slimline_shower_trays': _TRAY,
    'offset_quadrant_trays': _TRAY,
    'quadrant_trays': _TRAY,
    'square_trays': _TRAY,
    'slim_rectangular_trays': _TRAY,
    'slim_square_trays': _TRAY,
    'slim_quadrant_trays': _TRAY,
    'wetroom_trays': _TRAY,
    'd_shape_trays': _TRAY,

    # ── Enclosures & screens ─────────────────────
    'wetroom_screens': _SCREEN,
    'wetrooms': _SCREEN,
    'enclosures': _ENCLOSURE,
    'single_sliding_doors': _ENCLOSURE,
    'hinged_doors': _ENCLOSURE,
    'pivot_doors': _ENCLOSURE,
    'bi_fold_doors': _ENCLOSURE,
    'double_sliding_doors': _ENCLOSURE,
    'quadrants': _ENCLOSURE,
    'offset_quadrants': _ENCLOSURE,
    'corner_entry': _ENCLOSURE,
    'single_entry': _ENCLOSURE,
    'd_shape': _ENCLOSURE,
    'side_panels': _WH,
    'shower_enclosures': _ENCLOSURE,
    'enclosure_and_tray_packs': _ENCLOSURE,
    'enclosure_and_showering_packs': _ENCLOSURE,
    'wetroom_tray_packs': _SCREEN,

    # ── Bath screens ─────────────────────────────
    'bath_screens': _BATH_SCREEN,

    # ── Taps ─────────────────────────────────────
    'bath_fillers': _TAP,
    'bath_shower_mixers': _TAP,
    'mono_basin_taps': _TAP,
    'wall_mounted_basin_taps': _TAP,
    'tall_basin_taps': _TAP,
    'mini_basin_taps': _TAP,
    'pillar_taps': _TAP,
    'bidet_taps': _TAP,
    'bath_pillar_taps': _TAP,
    'kitchen_taps': _TAP,
    'sink_tap_packs': _TAP,
    'mixer_taps': _TAP,
    'taps': _TAP,
    'basin_taps': _TAP,
    'bath_taps': _TAP,
    'boiling_water_taps': _TAP,

    # ── Shower valves & controls ─────────────────
    '1_outlet_valves': _VALVE,
    '2_outlet_valves': _VALVE,
    '3_outlet_valves': _VALVE,
    'concealed_valves_sets': _VALVE,
    'exposed_valve_sets': _VALVE,
    'bar_shower_valves': _VALVE,
    'valve_kits': _VALVE,
    'shower_valves_and_controls': _VALVE,

    # ── Shower heads/arms/kits ───────────────────
    'fixed_heads': _SHOWER_HEAD,
    'shower_arms': _SHOWER_ARM,
    'shower_slide_rail_kits': _SHOWER_KIT,
    'hand_held_shower_kits': _SHOWER_KIT,
    'bar_mixer_shower_sets': _SHOWER_KIT,
    'complete_shower_sets': _SHOWER_KIT,
    'rigid_riser_kits': _SHOWER_KIT,
    'shower_kits': _SHOWER_KIT,
    'body_jets': _SHOWER_HEAD,

    # ── Toilets ──────────────────────────────────
    'close_coupled_toilets': _TOILET,
    'wall_hung_toilets': _TOILET,
    'back_to_wall_toilets': _TOILET,
    'pan_only': _TOILET,
    'cistern_only': _TOILET,
    'toilets': _TOILET,
    'toilet_seats': _CORE,
    'concealed_cisterns_and_frames': _CORE,
    'cloakroom_suites': _TOILET,
    'bathroom_suites': _TOILET,
    'toilet_and_basin_sets': _TOILET,
    'doc_m_packs': _TOILET,
    'bidets': _TOILET,

    # ── Radiators & towel rails ──────────────────
    'heated_towels_rails': _RADIATOR,
    'single_panel_radiators': _RADIATOR,
    'double_panel_radiators': _RADIATOR,
    'traditional_column_radiators': _RADIATOR,
    'electric_bar_towel_rails': _RADIATOR,
    'electric_flat_panel_towel_rails': _RADIATOR,
    'radiator_valves': _CORE,
    'heating': _RADIATOR,
    'heating_accessories': _CORE,

    # ── Mirrors ──────────────────────────────────
    'mirror_cabinets': _MIRROR,
    'framed_led_touch_sensor_mirrors': _WH,
    'led_touch_sensor': _WH,
    'unlit_mirrors': _WH,
    'single_door_mirror_cabinets': _MIRROR,
    'double_door_mirror_cabinets': _MIRROR,

    # ── Kitchen sinks ────────────────────────────
    'kitchen_sinks': _SINK,
    'butler_sink': _SINK,
    'belfast_sink': _SINK,
    'undermount_sinks': _SINK,
    'counter_top_sinks': _SINK,
    'cleaner_sinks': _SINK,
    'kitchen_inset_sink': _SINK,

    # ── Worktops ─────────────────────────────────
    'furniture_worktops': _WORKTOP,
    'furniture_worktops_and_basins': _WORKTOP,

    # ── Accessories & parts ──────────────────────
    'handles': _CORE,
    'basin_accessories': _CORE,
    'toilet_accessories': _CORE,
    'bath_wastes_and_extras': _CORE,
    'wastes': _CORE,
    'shower_tray_wastes': _CORE,
    'kitchen_wastes': _CORE,
    'kitchen_wastes_overflow': _CORE,
    'tap_extras': _CORE,
    'shower_parts': _CORE,
    'shower_accessories': _CORE,
    'enclosure_accessories': _CORE,
    'wetroom_accessories': _CORE,
    'tray_accessories': _CORE,
    'leg_sets_and_plinths': _CORE,
    'spare_parts': _CORE,
    'heating_extras': _CORE,
    'kitchen_extras': _CORE,
    'showers': _CORE,
    'marketplace_accessories': _CORE,
    'marketplace_enclosure_accessories': _CORE,
    'marketplace_showering': _CORE,
    'TBC': _CORE,
}

ISOMETRIC_CATEGORIES = {
    'freestanding_baths', 'single_ended_baths', 'double_ended_baths', 'back_to_wall_baths',
    'corner_baths', 'curved_baths', 'straight_baths', 'whirlpool_baths', 'baths',
    'square_shower_baths', 'p_shaped_shower_baths', 'b_shaped_shower_baths', 'shower_baths',
    'bathroom_suites', 'cloakroom_suites', 'toilet_and_basin_sets',
}

FURNITURE_CATEGORIES = {
    'furniture_floorstanding_vanities', 'furniture_wall_hung_vanities',
    'furniture_counter_top_vanities', 'vanity_units', 'cloakroom_vanities',
    'full_depth_furniture_packs', 'compact_furniture_pack', 'wc_units',
    'tall_units', 'fitted_units', 'wall_units', 'furniture_vanity_units',
    'floor_standing_vanities', 'furniture',
}

SUITE_CATEGORIES = {
    'bathroom_suites', 'cloakroom_suites', 'toilet_and_basin_sets',
}

DIMENSION_ATTRS = [
    ('product_width', 'W'),
    ('product_height', 'H'),
    ('product_length', 'L'),
    ('product_depth', 'D'),
    ('product_dia', 'Ø'),
    ('inner_bowl_depth', 'Bowl D'),
    ('inner_bowl_height', 'Bowl H'),
    ('inner_bowl_width', 'Bowl W'),
    ('entry_width', 'Entry W'),
    ('radius', 'R'),
    ('shower_head_dia', 'Head Ø'),
    ('tap_spout_height', 'Spout H'),
    ('tap_spout_projection', 'Spout P'),
    ('waste_pipe_dia', 'Waste Ø'),
    ('waste_pipe_length', 'Waste L'),
    ('tube_dia', 'Tube Ø'),
    ('hose_length', 'Hose L'),
    ('glass_thickness', 'Glass T'),
    ('fascia_thickness', 'Fascia T'),
    ('bath_mat_thickness', 'Bath Mat T'),
    ('cab_mat_thickness', 'Cab Mat T'),
    ('sink_thickness', 'Sink T'),
    ('sinks_flute_size', 'Flute'),
    ('sinks_rebate_size', 'Rebate'),
    ('swing_in', 'Swing In'),
    ('swing_out', 'Swing Out'),
    ('max_projection', 'Max P'),
    ('floor_centre_tappings', 'Floor-Tap'),
    ('wall_centre_tappings', 'Wall-Tap'),
    ('hinge_centres_min', 'Hinge Min'),
    ('hinge_centres_max', 'Hinge Max'),
    ('bath_void', 'Bath Void'),
    ('displaced_capacity', 'Disp Cap'),
]

UNIT_LABELS = {
    'MILLIMETER': 'mm',
    'CENTIMETER': 'cm',
    'METER': 'm',
    'LITER': 'L',
    'MILLILITER': 'mL',
    'INCH': 'in',
}

# ── Akeneo ──────────────────────────────────────────────────────────────────

def akeneo_auth():
    resp = requests.post(f'{AKENEO_URL}/api/oauth/v1/token', json={
        'grant_type': 'password',
        'client_id': AKENEO_CLIENT_ID,
        'client_secret': AKENEO_CLIENT_SECRET,
        'username': AKENEO_USERNAME,
        'password': AKENEO_PASSWORD,
    })
    resp.raise_for_status()
    return resp.json()['access_token']


def get_product(token, sku):
    headers = {'Authorization': f'Bearer {token}'}
    resp = requests.get(f'{AKENEO_URL}/api/rest/v1/products/{sku}', headers=headers)
    resp.raise_for_status()
    return resp.json()


def get_cutout_url(token, sku):
    headers = {'Authorization': f'Bearer {token}'}
    for code in [sku, sku.lower(), sku.upper()]:
        resp = requests.get(
            f'{AKENEO_URL}/api/rest/v1/asset-families/cutout_1/assets/{code}',
            headers=headers
        )
        if resp.status_code == 200:
            asset = resp.json()
            link_val = asset.get('values', {}).get('cutout_1_link', [])
            if link_val:
                return link_val[0]['data']
    return None


def get_line_drawing_url(token, sku):
    headers = {'Authorization': f'Bearer {token}'}
    for code in [sku, sku.lower(), sku.upper()]:
        resp = requests.get(
            f'{AKENEO_URL}/api/rest/v1/asset-families/line_drawing/assets/{code}',
            headers=headers, timeout=15
        )
        if resp.status_code == 200:
            asset = resp.json()
            link_val = asset.get('values', {}).get('line_drawing_link', [])
            if link_val:
                return link_val[0]['data']
    return None


def _parse_mm(val_str):
    if not val_str:
        return None
    m = re.match(r'([\d.]+)\s*(mm|cm|m)?', str(val_str).strip(), re.IGNORECASE)
    if not m:
        return None
    num = float(m.group(1))
    unit = (m.group(2) or 'mm').lower()
    if unit == 'cm':
        return num * 10
    if unit == 'm':
        return num * 1000
    return num


def compose_bom_sheet(components):
    """Composite component line drawings into a proportionate sheet using PIL."""
    from PIL import Image, ImageDraw, ImageFont
    import io

    parsed = []
    for comp in components:
        img = Image.open(io.BytesIO(comp['image_bytes'])).convert('RGBA')
        bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg.convert('RGB')
        w_mm = _parse_mm(comp['dims'].get('W')) or _parse_mm(comp['dims'].get('L')) or 500.0
        parsed.append({**comp, 'img': img, 'w_mm': w_mm})

    MAX_COMPONENT_W = 700
    max_w_mm = max(c['w_mm'] for c in parsed)
    ppm = MAX_COMPONENT_W / max_w_mm

    LABEL_H = 72
    PADDING = 48

    scaled = []
    for comp in parsed:
        target_w = max(int(comp['w_mm'] * ppm), 60)
        orig_w, orig_h = comp['img'].size
        target_h = max(int(orig_h * target_w / orig_w), 60)
        resized = comp['img'].resize((target_w, target_h), Image.LANCZOS)
        scaled.append({**comp, 'resized': resized, 'tw': target_w, 'th': target_h})

    COLS = min(len(scaled), 3)
    ROWS = (len(scaled) + COLS - 1) // COLS

    col_widths  = [max((scaled[i]['tw'] for i in range(col, len(scaled), COLS)), default=0) for col in range(COLS)]
    row_heights = [max(c['th'] for c in scaled[row * COLS:(row + 1) * COLS]) for row in range(ROWS)]

    canvas_w = sum(col_widths) + PADDING * (COLS + 1)
    canvas_h = sum(row_heights) + (LABEL_H + PADDING) * ROWS + PADDING

    canvas = Image.new('RGB', (canvas_w, canvas_h), 'white')
    draw   = ImageDraw.Draw(canvas)

    font_bold = font_normal = None
    for fp in ['C:/Windows/Fonts/calibrib.ttf', 'C:/Windows/Fonts/arialbd.ttf']:
        try:
            font_bold = ImageFont.truetype(fp, 15)
            break
        except Exception:
            pass
    for fp in ['C:/Windows/Fonts/calibri.ttf', 'C:/Windows/Fonts/arial.ttf']:
        try:
            font_normal = ImageFont.truetype(fp, 13)
            break
        except Exception:
            pass
    if font_bold is None:
        font_bold = ImageFont.load_default()
    if font_normal is None:
        font_normal = ImageFont.load_default()

    y = PADDING
    for row in range(ROWS):
        x = PADDING
        row_items = scaled[row * COLS:(row + 1) * COLS]
        for col_idx, comp in enumerate(row_items):
            col_w = col_widths[col_idx]
            x_img = x + (col_w - comp['tw']) // 2
            canvas.paste(comp['resized'], (x_img, y))

            label_y = y + row_heights[row] + 8
            draw.text((x, label_y),      comp['sku'],       fill='#111111', font=font_bold)
            dim_text = '  '.join(f"{k}: {v}" for k, v in comp['dims'].items())
            draw.text((x, label_y + 20), dim_text,          fill='#444444', font=font_normal)
            desc = (comp.get('description') or '')
            if desc and desc != comp['sku']:
                draw.text((x, label_y + 38), desc[:60],     fill='#888888', font=font_normal)

            x += col_w + PADDING
        y += row_heights[row] + LABEL_H + PADDING

    buf = io.BytesIO()
    canvas.save(buf, format='JPEG', quality=95, dpi=(150, 150))
    return buf.getvalue()


def get_dimensions(product, category=None):
    """Extract dimension attributes relevant to the product's category."""
    dims = {}
    values = product.get('values', {})
    attrs_to_use = CATEGORY_DIMS.get(category, _DEFAULT) if category else _DEFAULT

    for attr, label in attrs_to_use:
        val = values.get(attr)
        if val and val[0].get('data'):
            data = val[0]['data']
            amount = data.get('amount', '')
            unit = data.get('unit', 'MILLIMETER')
            if amount:
                num = float(amount)
                num_str = str(int(num)) if num == int(num) else f'{num:.1f}'
                unit_str = UNIT_LABELS.get(unit, unit.lower())
                dims[label] = f'{num_str}{unit_str}'

    return dims


def get_product_contents(product):
    values = product.get('values', {})
    info = {}

    comp_val = values.get('components_included', [])
    if comp_val and comp_val[0].get('data'):
        info['includes'] = comp_val[0]['data'].strip('"')

    bom_val = values.get('Boms_Data_Table', [])
    if bom_val and bom_val[0].get('data'):
        components = [row.get('Component_Description', '') for row in bom_val[0]['data'] if row.get('Component_Description')]
        if components:
            info['components'] = components

    waste_val = values.get('includes_waste', [])
    if waste_val and waste_val[0].get('data') is not None:
        info['includes_waste'] = waste_val[0]['data']

    return info


def get_product_model(token, sku):
    try:
        product = get_product(token, sku)
        return product.get('parent')
    except Exception:
        return None


def get_model_variants(token, model_code):
    headers = {'Authorization': f'Bearer {token}'}
    skus = []
    url = f'{AKENEO_URL}/api/rest/v1/products'
    params = {
        'search': json.dumps({'parent': [{'operator': '=', 'value': model_code}]}),
        'limit': 100,
        'pagination_type': 'search_after',
    }
    while url:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        if resp.status_code != 200:
            break
        data = resp.json()
        skus.extend(p['identifier'] for p in data.get('_embedded', {}).get('items', []))
        url = data.get('_links', {}).get('next', {}).get('href')
        params = None
    return skus


# ── S3 ──────────────────────────────────────────────────────────────────────

def upload_to_s3(image_bytes, prefix='cutout'):
    s3 = boto3.client(
        's3',
        region_name=AWS_REGION,
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID', ''),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY', ''),
        config=BotoConfig(signature_version='s3v4'),
    )
    key = f'linedrawing-temp/{prefix}_{uuid.uuid4().hex[:8]}.jpg'
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=image_bytes, ContentType='image/jpeg')
    url = s3.generate_presigned_url('get_object', Params={'Bucket': S3_BUCKET, 'Key': key}, ExpiresIn=3600)
    return url


# ── Prompts ──────────────────────────────────────────────────────────────────

def build_prompt(dimensions, contents=None, view_hint=None):
    dim_text = ', '.join(f'{label}: {val}' for label, val in dimensions.items())

    exclusions = []
    if contents:
        includes = contents.get('includes', '').lower()
        components = [c.lower() for c in contents.get('components', [])]
        all_text = includes + ' ' + ' '.join(components)

        if not any(word in all_text for word in ['tap', 'mixer', 'faucet']):
            exclusions.append('taps')
        if not contents.get('includes_waste', False) and 'waste' not in all_text:
            exclusions.append('waste fittings')
        if not any(word in all_text for word in ['mirror']):
            exclusions.append('mirrors')

    exclusion_text = ''
    if exclusions:
        exclusion_text = f'\n- This product does NOT include: {", ".join(exclusions)}. Do NOT draw these items.'

    dim_instructions = ''
    if dim_text:
        if view_hint == 'furniture':
            dim_instructions = f"""
- Add dimension annotation lines with arrows for ONLY these measurements: {dim_text}
- CRITICAL: each dimension line must span the COMPLETE overall extent of the product in that direction
- Dimension placement — follow this EXACTLY every time, no exceptions:
  * W (width): horizontal dimension line positioned BELOW the product at the base, arrows spanning the full width left-to-right, label centred below
  * H (height): vertical dimension line positioned to the LEFT of the product, arrows spanning the full height top-to-bottom, label to the left
  * D (depth): dimension line along the oblique bottom-left edge showing cabinet depth, label at the bottom-left corner
- All dimension lines must sit OUTSIDE the product outline, connected by clean perpendicular extension lines
- Dimension labels show ONLY the number and unit (e.g. "600mm") — no letter prefixes like "W:" or "H:"
- Use standard technical drawing conventions: thin lines for dimensions, thicker lines for the product outline"""
        else:
            dim_instructions = f"""
- Add dimension annotation lines with arrows for ONLY these measurements: {dim_text}
- CRITICAL: each dimension line must span the COMPLETE overall extent of the product in that direction — from the absolute outermost edge to the absolute outermost edge of the bounding box. Never annotate a partial or internal measurement.
- Dimension lines must be placed OUTSIDE the product outline with extension lines, not inside or overlapping the drawing
- Stagger multiple dimension lines at different offsets from the outline so they do not overlap each other
- Dimension labels show ONLY the number and unit (e.g. "1595mm") — no letter prefixes like "W:" or descriptive text
- If a dimension cannot be accurately shown in the chosen view, omit it entirely rather than placing it incorrectly"""

    view_instruction = 'Single view of the product matching the angle shown in the photo'
    if view_hint == 'isometric':
        view_instruction = ('Draw the product from a slight 3/4 isometric perspective angle (top-front-side visible) '
                            'so that the length, width, and height can all be shown as separate dimension annotations. '
                            'Base the shape and proportions on the product photo provided')
    elif view_hint == 'furniture':
        view_instruction = (
            'Draw the product as a standard furniture/cabinet technical elevation: '
            'the front face shown straight-on (full face visible, no foreshortening) with '
            'the top surface and one side edge visible at a consistent oblique angle — '
            'exactly like a professional furniture spec drawing. '
            'Accurately reproduce all cabinet details visible in the photo: '
            'door panels, handles, hinges, plinth, basin or worktop lip if present. '
            'Base the shape and proportions exactly on the product photo provided'
        )

    prompt = f"""Convert this product photo into a clean technical line drawing / engineering diagram.

Requirements:
- Pure black outlines on a white background
- {view_instruction}
- ONLY draw the product itself — do NOT add or invent any extra items, fixtures or accessories that are not part of this product{exclusion_text}{dim_instructions}
- Use standard technical drawing conventions (thin lines for dimensions, thicker lines for the product outline)
- Clean, professional, publication-ready quality
- No shading, no colour, no gradients — only black line work on white
- The drawing should accurately represent the product's shape and proportions from the cutout photo provided"""

    return prompt


def build_bom_prompt(main_sku, main_dims, components_info):
    main_dim_text = ', '.join(f'{val}' for val in main_dims.values())

    comp_sections = []
    for i, comp in enumerate(components_info, 1):
        comp_dim_text = ', '.join(f'{val}' for val in comp['dims'].values())
        comp_sections.append(f"Component {i}: {comp['description']} — dimensions: {comp_dim_text}")

    comp_text = '\n'.join(comp_sections)

    prompt = f"""Create a single technical line drawing sheet showing multiple views of a product and its components.

I am providing {len(components_info) + 1} reference photos. The FIRST photo is the fully assembled product. The remaining photos are the individual components.

Layout the drawing as follows:
- Show each individual component as a separate line drawing with its own dimensions
- Show the fully assembled product as a larger line drawing with overall dimensions
- Arrange all views on a single white canvas — components along the top or side, assembled view prominently displayed

Component details:
{comp_text}

Assembled product dimensions: {main_dim_text}

Requirements:
- Pure black outlines on a white background
- ONLY draw what is visible in each photo — do NOT add taps, fixtures or accessories not shown
- Dimension labels should show ONLY the number and unit (e.g. "810mm") — no descriptive text
- Dimension lines with arrows positioned outside product outlines
- Standard technical drawing conventions (thin dimension lines, thicker product outlines)
- Clean, professional, publication-ready quality
- No shading, no colour, no gradients — only black line work on white"""

    return prompt


# ── Generation ───────────────────────────────────────────────────────────────

def generate_line_drawing(cutout_url, dimensions, contents=None, view_hint=None):
    """Send cutout + dimensions to kie.ai and return the generated image bytes."""
    dl_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    cutout_resp = requests.get(cutout_url, headers=dl_headers, timeout=30)
    if cutout_resp.status_code != 200:
        raise Exception(f'Failed to download cutout: {cutout_resp.status_code}')

    s3_url = upload_to_s3(cutout_resp.content)
    prompt = build_prompt(dimensions, contents, view_hint=view_hint)

    payload = {
        'model': KIE_MODEL,
        'input': {
            'prompt': prompt,
            'image_input': [s3_url],
            'aspect_ratio': '1:1',
            'resolution': '2K',
            'output_format': 'png',
        }
    }
    headers = {
        'Authorization': f'Bearer {KIE_API_KEY}',
        'Content-Type': 'application/json',
    }

    resp = requests.post(KIE_API_URL, json=payload, headers=headers, timeout=30)
    data = resp.json()
    if data.get('code') != 200:
        raise Exception(f'kie.ai createTask failed: {data.get("msg", resp.text)}')

    task_id = data['data']['taskId']

    elapsed = 0
    max_wait = 600
    poll_interval = 5

    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval

        poll_resp = requests.get(
            KIE_POLL_URL,
            params={'taskId': task_id},
            headers={'Authorization': f'Bearer {KIE_API_KEY}'},
            timeout=15,
        )
        poll_data = poll_resp.json()

        if poll_data.get('code') != 200:
            continue

        state = poll_data['data'].get('state', '')

        if state == 'success':
            result_json = poll_data['data'].get('resultJson', '{}')
            if isinstance(result_json, str):
                result_json = json.loads(result_json)
            result_urls = result_json.get('resultUrls', [])
            if result_urls:
                img_resp = requests.get(result_urls[0], timeout=60)
                return img_resp.content
            raise Exception('Task succeeded but no result URLs')

        elif state == 'fail':
            fail_msg = poll_data['data'].get('failMsg', 'Unknown')
            raise Exception(f'Generation failed: {fail_msg}')

    raise Exception(f'Task timed out after {max_wait}s')


def generate_bom_line_drawing(main_cutout_url, main_dims, component_cutout_urls, components_info):
    """Generate a multi-view line drawing for a BOM product with components."""
    dl_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    image_urls = []

    resp = requests.get(main_cutout_url, headers=dl_headers, timeout=30)
    if resp.status_code != 200:
        raise Exception(f'Failed to download main cutout: {resp.status_code}')
    image_urls.append(upload_to_s3(resp.content, prefix='assembled'))

    for i, url in enumerate(component_cutout_urls):
        resp = requests.get(url, headers=dl_headers, timeout=30)
        if resp.status_code != 200:
            continue
        image_urls.append(upload_to_s3(resp.content, prefix=f'comp{i+1}'))

    prompt = build_bom_prompt(None, main_dims, components_info)

    payload = {
        'model': KIE_MODEL,
        'input': {
            'prompt': prompt,
            'image_input': image_urls,
            'aspect_ratio': '16:9',
            'resolution': '2K',
            'output_format': 'png',
        }
    }
    headers = {
        'Authorization': f'Bearer {KIE_API_KEY}',
        'Content-Type': 'application/json',
    }

    resp = requests.post(KIE_API_URL, json=payload, headers=headers, timeout=30)
    data = resp.json()
    if data.get('code') != 200:
        raise Exception(f'kie.ai createTask failed: {data.get("msg", resp.text)}')

    task_id = data['data']['taskId']

    elapsed = 0
    max_wait = 600
    poll_interval = 5

    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval

        poll_resp = requests.get(
            KIE_POLL_URL,
            params={'taskId': task_id},
            headers={'Authorization': f'Bearer {KIE_API_KEY}'},
            timeout=15,
        )
        poll_data = poll_resp.json()

        if poll_data.get('code') != 200:
            continue

        state = poll_data['data'].get('state', '')

        if state == 'success':
            result_json = poll_data['data'].get('resultJson', '{}')
            if isinstance(result_json, str):
                result_json = json.loads(result_json)
            result_urls = result_json.get('resultUrls', [])
            if result_urls:
                img_resp = requests.get(result_urls[0], timeout=60)
                return img_resp.content
            raise Exception('Task succeeded but no result URLs')

        elif state == 'fail':
            fail_msg = poll_data['data'].get('failMsg', 'Unknown')
            raise Exception(f'Generation failed: {fail_msg}')

    raise Exception(f'Task timed out after {max_wait}s')
