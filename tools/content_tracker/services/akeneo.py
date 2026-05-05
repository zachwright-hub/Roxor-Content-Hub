# Akeneo API Client — Asset Health Monitor
# ==========================================
# Based on brief generator AkeneoClient, extended with asset family methods.

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
        self._session = requests.Session()  # Reuse TCP connections for speed

    def get_token(self, force=False):
        """OAuth2 password grant. Caches token until near-expiry."""
        if not force and self.token and self.token_expiry and datetime.now() < self.token_expiry:
            return self.token

        print('Authenticating with Akeneo...')

        auth_string = base64.b64encode(f'{self.client_id}:{self.client_secret}'.encode()).decode()

        response = requests.post(
            f'{self.base_url}/api/oauth/v1/token',
            json={
                'grant_type': 'password',
                'username': self.username,
                'password': self.password
            },
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Basic {auth_string}'
            }
        )

        if response.status_code != 200:
            raise Exception(f'Akeneo authentication failed: {response.text}')

        data = response.json()
        self.token = data['access_token']
        self.token_expiry = datetime.now() + timedelta(seconds=data['expires_in'] - 60)

        print('Akeneo authentication successful')
        return self.token

    def _request(self, method, url, **kwargs):
        """Make an authenticated request with automatic token refresh on 401."""
        token = self.get_token()
        kwargs.setdefault('headers', {})
        kwargs['headers']['Authorization'] = f'Bearer {token}'
        kwargs['headers'].setdefault('Content-Type', 'application/json')
        kwargs.setdefault('timeout', 30)

        resp = self._session.request(method, url, **kwargs)

        if resp.status_code == 401:
            token = self.get_token(force=True)
            kwargs['headers']['Authorization'] = f'Bearer {token}'
            resp = self._session.request(method, url, **kwargs)

        return resp

    def get_product(self, sku):
        """Fetch a single product by SKU."""
        try:
            resp = self._request(
                'GET',
                f'{self.base_url}/api/rest/v1/products/{requests.utils.quote(sku, safe="")}'
            )

            if resp.status_code == 404:
                return None

            if resp.status_code != 200:
                print(f'Error fetching {sku}: {resp.status_code}')
                return None

            return resp.json()

        except Exception as e:
            print(f'Error fetching {sku}: {e}')
            return None

    def get_products(self, skus, on_progress=None):
        """Fetch multiple products one by one."""
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
        """Get attribute value with locale/scope fallback chain."""
        if not product or 'values' not in product or attribute_code not in product['values']:
            return None

        values = product['values'][attribute_code]

        # Try locale + scope specific
        for v in values:
            if v.get('locale') == locale and v.get('scope') == scope:
                return v.get('data')

        # Try locale specific
        for v in values:
            if v.get('locale') == locale:
                return v.get('data')

        # Try scope specific
        for v in values:
            if v.get('scope') == scope:
                return v.get('data')

        # Return first value
        if values:
            return values[0].get('data')

        return None

    def get_attribute_option_label(self, attribute_code, option_code, locale='en_GB'):
        """Get the human-readable label for an attribute option code."""
        if not option_code:
            return option_code or ''
        try:
            resp = self._request(
                'GET',
                f'{self.base_url}/api/rest/v1/attributes/{attribute_code}/options/{requests.utils.quote(str(option_code), safe="")}'
            )
            if resp.status_code == 200:
                data = resp.json()
                labels = data.get('labels', {})
                if labels:
                    return labels.get(locale) or labels.get('en_US') or next(iter(labels.values()), option_code)
                return option_code
            return option_code
        except Exception as e:
            print(f'Error fetching option label for {attribute_code}/{option_code}: {e}')
            return option_code

    def get_all_products(self, on_progress=None):
        """Paginate through ALL products using search_after cursor. Returns full list."""
        products = []
        url = f'{self.base_url}/api/rest/v1/products?limit=100&pagination_type=search_after'
        page = 0

        while url:
            try:
                resp = self._request('GET', url)

                if resp.status_code != 200:
                    print(f'Akeneo API error: {resp.status_code}')
                    break

                data = resp.json()
                items = data.get('_embedded', {}).get('items', [])

                if not items:
                    break

                products.extend(items)
                page += 1

                if on_progress:
                    on_progress(len(products))

                if page % 10 == 0:
                    print(f'[Akeneo] Fetched {len(products)} products...')

                next_link = data.get('_links', {}).get('next', {}).get('href')
                url = next_link if next_link else None

            except Exception as e:
                print(f'Akeneo pagination error: {e}')
                break

        print(f'[Akeneo] Total products fetched: {len(products)}')
        return products

    # ------------------------------------------------------------------
    # Asset family methods (new for Asset Health Monitor)
    # ------------------------------------------------------------------

    def get_asset_families(self):
        """List all asset families. Returns list of family dicts."""
        url = f'{self.base_url}/api/rest/v1/asset-families'
        resp = self._request('GET', url)
        if resp.status_code != 200:
            print(f'Error fetching asset families: {resp.status_code}')
            return []
        data = resp.json()
        return data.get('_embedded', {}).get('items', [])

    def get_assets_for_family(self, family_code, on_page=None):
        """
        Generator yielding pages of assets for a given asset family.
        Uses search_after pagination (100/page) to avoid memory issues.
        Calls on_page(page_assets, total_so_far) callback if provided.

        Each asset dict has: code, values (with sales_code, media_link attributes)
        """
        url = f'{self.base_url}/api/rest/v1/asset-families/{family_code}/assets'
        params = {'limit': 100}
        total = 0

        while url:
            resp = self._request('GET', url, params=params)

            if resp.status_code != 200:
                print(f'Error fetching assets for {family_code}: {resp.status_code}')
                break

            data = resp.json()
            items = data.get('_embedded', {}).get('items', [])

            if not items:
                break

            total += len(items)
            if on_page:
                on_page(items, total)

            yield items

            # Get next page — URL already contains params
            next_link = data.get('_links', {}).get('next', {}).get('href')
            url = next_link if next_link else None
            params = None  # params already encoded in the next URL

            del data, items

    def get_products_by_skus(self, skus):
        """Fetch products by SKU list, returning dict of SKU -> {brand, family}.
        Uses Akeneo search filter with IN operator. Batches of 100."""
        result = {}
        sku_list = list(set(s for s in skus if s))
        if not sku_list:
            return result

        for i in range(0, len(sku_list), 100):
            batch = sku_list[i:i + 100]
            import json as _json
            search = _json.dumps({'identifier': [{'operator': 'IN', 'value': batch}]})
            url = f'{self.base_url}/api/rest/v1/products'
            params = {'search': search, 'limit': 100}

            try:
                resp = self._request('GET', url, params=params)
                if resp.status_code != 200:
                    print(f'[Akeneo] Bulk product fetch error: {resp.status_code}')
                    continue

                data = resp.json()
                for product in data.get('_embedded', {}).get('items', []):
                    sku = product.get('identifier', '')
                    family = product.get('family', '')
                    # Get brand from values
                    brand = ''
                    brand_values = product.get('values', {}).get('brand', [])
                    if brand_values:
                        brand = brand_values[0].get('data', '') if isinstance(brand_values[0], dict) else str(brand_values[0])
                    # Check marketplace (live_on_cs_cart)
                    marketplace = False
                    mp_values = product.get('values', {}).get('live_on_cs_cart', [])
                    if mp_values:
                        mp_data = mp_values[0].get('data', False) if isinstance(mp_values[0], dict) else mp_values[0]
                        marketplace = bool(mp_data)
                    result[sku] = {'brand': brand, 'family': family, 'marketplace': marketplace}
            except Exception as e:
                print(f'[Akeneo] Bulk product fetch error: {e}')

        print(f'[Akeneo] Bulk lookup: {len(result)}/{len(sku_list)} products found')
        return result

    def get_all_products_streaming(self, on_page=None, search=None):
        """
        Generator yielding pages of products for coverage scanning.
        Uses search_after pagination. Each page is a list of product dicts.
        Memory-efficient: only one page in memory at a time.

        search: optional Akeneo search JSON string, e.g.
            '{"brand":[{"operator":"=","value":"balterley"}]}'
        """
        url = f'{self.base_url}/api/rest/v1/products'
        params = {'limit': 100, 'pagination_type': 'search_after'}
        if search:
            params['search'] = search
        total = 0

        while url:
            resp = self._request('GET', url, params=params)

            if resp.status_code != 200:
                print(f'Akeneo API error: {resp.status_code}')
                break

            data = resp.json()
            items = data.get('_embedded', {}).get('items', [])

            if not items:
                break

            total += len(items)
            if on_page:
                on_page(items, total)

            yield items

            next_link = data.get('_links', {}).get('next', {}).get('href')
            url = next_link if next_link else None
            params = None

            del data, items

    def get_asset_cdn_url(self, family_code, asset_code):
        """
        Fetch a single asset from Akeneo Asset Manager and return its CDN URL.
        Returns the media_link URL string, or None if not found.
        """
        try:
            resp = self._request(
                'GET',
                f'{self.base_url}/api/rest/v1/asset-families/{family_code}/assets/{requests.utils.quote(asset_code, safe="")}'
            )
            if resp.status_code != 200:
                print(f'[Akeneo] Asset {asset_code} in {family_code}: HTTP {resp.status_code}')
                return None

            asset = resp.json()
            values = asset.get('values', {})
            for key in ['media_link', 'media']:
                if key in values:
                    val = values[key]
                    if isinstance(val, list) and val:
                        item = val[0]
                        url = item.get('data', '') if isinstance(item, dict) else str(item)
                        if url:
                            return url
                    elif isinstance(val, dict):
                        url = val.get('data', '')
                        if url:
                            return url
                    elif isinstance(val, str) and val:
                        return val
            return None
        except Exception as e:
            print(f'[Akeneo] Error fetching asset CDN URL for {family_code}/{asset_code}: {e}')
            return None

    def create_asset(self, family_code, asset_code, media_link, sku):
        """
        Create (upsert) an asset in Akeneo Asset Manager with a media_link and sales_code.
        Uses PATCH /api/rest/v1/asset-families/{family}/assets/{code}.
        Returns True on success, False on failure.
        """
        body = {
            'code': asset_code,
            'values': {
                'media_link': [{'data': media_link, 'locale': None, 'channel': None}],
                'sales_code': [{'data': sku, 'locale': None, 'channel': None}],
            }
        }

        try:
            resp = self._request(
                'PATCH',
                f'{self.base_url}/api/rest/v1/asset-families/{family_code}/assets/{requests.utils.quote(asset_code, safe="")}',
                json=body
            )
            if resp.status_code in (200, 201, 204):
                print(f'[Akeneo] Created/updated asset {asset_code} in {family_code}')
                return True
            else:
                print(f'[Akeneo] Failed to create asset {asset_code}: HTTP {resp.status_code} - {resp.text[:200]}')
                return False
        except Exception as e:
            print(f'[Akeneo] Error creating asset {asset_code}: {e}')
            return False

    def link_asset_to_product(self, sku, family_code, asset_code):
        """
        Link an asset to a product by adding the asset code to the product's
        asset collection attribute (e.g., cutout_1, lifestyle_1, etc.).
        Returns True on success, False on failure.
        """
        # First, get the current product to read existing asset codes
        product = self.get_product(sku)
        if not product:
            print(f'[Akeneo] Cannot link asset: product {sku} not found')
            return False

        # Get current asset codes for this family attribute
        values = product.get('values', {})
        current_assets = []
        if family_code in values:
            for entry in values[family_code]:
                data = entry.get('data', [])
                if isinstance(data, list):
                    current_assets = list(data)
                break

        # Check if already linked
        if asset_code in current_assets:
            print(f'[Akeneo] Asset {asset_code} already linked to {sku}/{family_code}')
            return True

        # Add the asset code
        current_assets.append(asset_code)

        # PATCH the product
        patch_body = {
            'values': {
                family_code: [
                    {'data': current_assets, 'locale': None, 'scope': None}
                ]
            }
        }

        try:
            resp = self._request(
                'PATCH',
                f'{self.base_url}/api/rest/v1/products/{requests.utils.quote(sku, safe="")}',
                json=patch_body
            )
            if resp.status_code in (200, 201, 204):
                print(f'[Akeneo] Linked {asset_code} to {sku}/{family_code}')
                return True
            else:
                print(f'[Akeneo] Failed to link {asset_code} to {sku}: HTTP {resp.status_code} - {resp.text[:200]}')
                return False
        except Exception as e:
            print(f'[Akeneo] Error linking {asset_code} to {sku}: {e}')
            return False
