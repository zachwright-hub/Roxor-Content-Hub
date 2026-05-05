import os
import requests
from datetime import datetime, timedelta


class AkeneoClient:
    def __init__(self):
        self.url = os.environ['AKENEO_URL'].rstrip('/')
        self.client_id = os.environ['AKENEO_CLIENT_ID']
        self.client_secret = os.environ['AKENEO_CLIENT_SECRET']
        self.username = os.environ['AKENEO_USERNAME']
        self.password = os.environ['AKENEO_PASSWORD']
        self._token = None
        self._token_expiry = None

    def _get_token(self):
        if self._token and self._token_expiry and datetime.now() < self._token_expiry:
            return self._token
        resp = requests.post(
            f'{self.url}/api/oauth/v1/token',
            json={
                'grant_type': 'password',
                'username': self.username,
                'password': self.password,
            },
            auth=(self.client_id, self.client_secret),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data['access_token']
        self._token_expiry = datetime.now() + timedelta(seconds=data.get('expires_in', 3600) - 60)
        return self._token

    def get(self, endpoint, params=None):
        headers = {'Authorization': f'Bearer {self._get_token()}'}
        resp = requests.get(f'{self.url}{endpoint}', headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def patch(self, endpoint, data):
        headers = {
            'Authorization': f'Bearer {self._get_token()}',
            'Content-Type': 'application/json',
        }
        resp = requests.patch(f'{self.url}{endpoint}', headers=headers, json=data, timeout=30)
        resp.raise_for_status()
        return resp

    def get_all_pages(self, endpoint, params=None):
        params = params or {}
        params.setdefault('limit', 100)
        results = []
        next_url = f'{self.url}{endpoint}'
        while next_url:
            headers = {'Authorization': f'Bearer {self._get_token()}'}
            resp = requests.get(next_url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            results.extend(data.get('_embedded', {}).get('items', []))
            next_url = data.get('_links', {}).get('next', {}).get('href')
            params = None
        return results
