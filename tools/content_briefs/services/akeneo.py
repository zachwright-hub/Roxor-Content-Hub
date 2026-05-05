import requests
import base64
from datetime import datetime, timedelta


class AkeneoClient:
    def __init__(self, config):
        self.base_url     = config['base_url']
        self.client_id    = config['client_id']
        self.client_secret = config['client_secret']
        self.username     = config['username']
        self.password     = config['password']
        self.token        = None
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
            raise Exception(f'Akeneo auth failed: {response.text}')
        data = response.json()
        self.token = data['access_token']
        self.token_expiry = datetime.now() + timedelta(seconds=data['expires_in'] - 60)
        return self.token

    def get_product(self, sku):
        token = self.get_token()
        try:
            resp = requests.get(
                f'{self.base_url}/api/rest/v1/products/{requests.utils.quote(sku, safe="")}',
                headers={'Authorization': f'Bearer {token}'},
                timeout=15
            )
            if resp.status_code == 404:
                return None
            if resp.status_code != 200:
                return None
            return resp.json()
        except Exception as e:
            print(f'[ContentBriefs] Error fetching {sku}: {e}')
            return None

    def get_products(self, skus):
        results = {}
        for sku in skus:
            product = self.get_product(sku)
            if product:
                results[sku] = product
        return results

    def get_product_values(self, product, sku, scoped_attrs, locale_attrs, extra_attrs, reference_attrs=None):
        """
        Returns a structured dict of current Akeneo values for use in the brief spreadsheet.

        scoped_attrs:    {"scope_code": ["attr1", "attr2"]}
        locale_attrs:    {"locale_code": ["attr1", "attr2"]}
        extra_attrs:     ["attr1", "attr2"]  (global, non-scoped non-locale)
        reference_attrs: ["attr1", "attr2"]  (context-only — pre-filled, not for writing)
        """
        result = {
            'sku': sku,
            'found': product is not None,
            'values': {'scoped': {}, 'locale': {}, 'extra': {}, 'reference': {}},
        }

        raw = product.get('values', {}) if product else {}

        for scope, attrs in scoped_attrs.items():
            result['values']['scoped'][scope] = {}
            for attr in attrs:
                val = self._get_value(raw, attr, scope=scope, locale=None)
                result['values']['scoped'][scope][attr] = self._stringify(val)

        for locale, attrs in locale_attrs.items():
            result['values']['locale'][locale] = {}
            for attr in attrs:
                val = self._get_value(raw, attr, scope=None, locale=locale)
                result['values']['locale'][locale][attr] = self._stringify(val)

        for attr in extra_attrs:
            val = self._get_value(raw, attr, scope=None, locale=None)
            result['values']['extra'][attr] = self._stringify(val)

        for attr in (reference_attrs or []):
            val = self._get_value(raw, attr, scope=None, locale=None)
            result['values']['reference'][attr] = self._stringify(val)

        return result

    def _get_value(self, values, attr_code, scope=None, locale=None):
        if attr_code not in values:
            return None
        entries = values[attr_code]
        # Exact match
        for e in entries:
            if e.get('scope') == scope and e.get('locale') == locale:
                return e.get('data')
        # Scope match only (attr is scope+locale, we matched scope)
        if scope:
            for e in entries:
                if e.get('scope') == scope:
                    return e.get('data')
        # Locale match only
        if locale:
            for e in entries:
                if e.get('locale') == locale:
                    return e.get('data')
        # Fallback: first entry
        return entries[0].get('data') if entries else None

    def _stringify(self, val):
        if val is None:
            return ''
        if isinstance(val, list):
            return '\n'.join(str(v) for v in val) if val else ''
        if isinstance(val, bool):
            return 'Yes' if val else 'No'
        return str(val)

    # ── Metadata endpoints ────────────────────────────────────────────────────

    def get_all_attributes(self):
        """Fetch all attributes, paginated. Returns list of {code, label, scopable, localizable, type}."""
        token = self.get_token()
        attrs = []
        url   = f'{self.base_url}/api/rest/v1/attributes?limit=100'
        while url:
            try:
                resp = requests.get(url, headers={'Authorization': f'Bearer {token}'}, timeout=30)
                if resp.status_code != 200:
                    break
                data  = resp.json()
                items = data.get('_embedded', {}).get('items', [])
                for item in items:
                    labels = item.get('labels', {})
                    label  = (labels.get('en_GB') or labels.get('en_US') or
                              next(iter(labels.values()), None) or item['code'])
                    attrs.append({
                        'code':        item['code'],
                        'label':       label,
                        'type':        item.get('type', ''),
                        'scopable':    item.get('scopable', False),
                        'localizable': item.get('localizable', False),
                    })
                next_href = data.get('_links', {}).get('next', {}).get('href')
                url = next_href if next_href and next_href != url else None
            except Exception as e:
                print(f'[ContentBriefs] get_all_attributes error: {e}')
                break
        return attrs

    def get_channels(self):
        """Fetch all channels (scopes)."""
        token = self.get_token()
        try:
            resp = requests.get(
                f'{self.base_url}/api/rest/v1/channels?limit=100',
                headers={'Authorization': f'Bearer {token}'}, timeout=15
            )
            if resp.status_code != 200:
                return []
            items = resp.json().get('_embedded', {}).get('items', [])
            return [
                {'code': c['code'],
                 'label': (c.get('labels', {}).get('en_GB') or
                           c.get('labels', {}).get('en_US') or c['code'])}
                for c in items
            ]
        except Exception as e:
            print(f'[ContentBriefs] get_channels error: {e}')
            return []

    def get_active_locales(self):
        """Fetch enabled locales."""
        token = self.get_token()
        try:
            resp = requests.get(
                f'{self.base_url}/api/rest/v1/locales?limit=100',
                headers={'Authorization': f'Bearer {token}'}, timeout=15
            )
            if resp.status_code != 200:
                return []
            items = resp.json().get('_embedded', {}).get('items', [])
            return [{'code': l['code']} for l in items if l.get('enabled', True)]
        except Exception as e:
            print(f'[ContentBriefs] get_active_locales error: {e}')
            return []
