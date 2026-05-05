import requests
import base64
from datetime import datetime, timedelta


class AkeneoClient:
    def __init__(self, config):
        self.base_url = config['base_url']
        self.client_id = config['client_id']
        self.client_secret = config['client_secret']
        self.username = config['username']
        self.password = config['password']
        self.token = None
        self.token_expiry = None

    def get_token(self, force=False):
        if not force and self.token and self.token_expiry and datetime.now() < self.token_expiry:
            return self.token
        auth_string = base64.b64encode(f'{self.client_id}:{self.client_secret}'.encode()).decode()
        response = requests.post(
            f'{self.base_url}/api/oauth/v1/token',
            json={'grant_type': 'password', 'username': self.username, 'password': self.password},
            headers={'Content-Type': 'application/json', 'Authorization': f'Basic {auth_string}'}
        )
        if response.status_code != 200:
            raise Exception(f'Akeneo authentication failed: {response.text}')
        data = response.json()
        self.token = data['access_token']
        self.token_expiry = datetime.now() + timedelta(seconds=data['expires_in'] - 60)
        return self.token

    def get_product(self, sku):
        token = self.get_token()
        try:
            response = requests.get(
                f'{self.base_url}/api/rest/v1/products/{requests.utils.quote(sku, safe="")}',
                headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
            )
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                return None
            return response.json()
        except Exception as e:
            print(f'Error fetching {sku}: {e}')
            return None

    def get_products(self, skus, on_progress=None):
        results = {}
        total = len(skus)
        for i, sku in enumerate(skus):
            product = self.get_product(sku)
            if product:
                results[sku] = product
            if on_progress:
                on_progress(i + 1, total, sku)
        return results

    def get_attribute(self, product, attribute_code, locale='en_GB', scope='ecommerce'):
        if not product or 'values' not in product or attribute_code not in product['values']:
            return None
        values = product['values'][attribute_code]
        for v in values:
            if v.get('locale') == locale and v.get('scope') == scope:
                return v.get('data')
        for v in values:
            if v.get('locale') == locale:
                return v.get('data')
        for v in values:
            if v.get('scope') == scope:
                return v.get('data')
        if values:
            return values[0].get('data')
        return None

    def get_attribute_option_label(self, attribute_code, option_code, locale='en_GB'):
        if not option_code:
            return option_code or ''
        try:
            token = self.get_token()
            resp = requests.get(
                f'{self.base_url}/api/rest/v1/attributes/{attribute_code}/options/{requests.utils.quote(str(option_code), safe="")}',
                headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                labels = data.get('labels', {})
                return labels.get(locale) or labels.get('en_US') or next(iter(labels.values()), option_code) if labels else option_code
            return option_code
        except Exception:
            return option_code

    def get_asset_url(self, product, attribute_code, asset_family=None, locale='en_GB', scope='ecommerce'):
        asset_codes = self.get_attribute(product, attribute_code, locale, scope)
        if not asset_codes:
            return ''
        if isinstance(asset_codes, list) and asset_codes:
            asset_code = asset_codes[0]
        elif isinstance(asset_codes, str):
            asset_code = asset_codes
        else:
            return ''
        family = asset_family or attribute_code
        try:
            token = self.get_token()
            resp = requests.get(
                f'{self.base_url}/api/rest/v1/asset-families/{family}/assets/{asset_code}',
                headers={'Authorization': f'Bearer {token}'}
            )
            if resp.status_code == 200:
                asset = resp.json()
                for key, values in asset.get('values', {}).items():
                    for v in values:
                        if v.get('attribute_type') == 'media_link' and v.get('data'):
                            return v['data']
        except Exception as e:
            print(f'Error fetching asset {asset_code}: {e}')
        return ''
