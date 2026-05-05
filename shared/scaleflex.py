import os
import requests


class ScaleflexClient:
    def __init__(self):
        self.workspace = os.environ.get('SCALEFLEX_WORKSPACE', 'xa38qjmpah')
        self.api_key = os.environ['SCALEFLEX_API_KEY']
        self.base_url = f'https://api.filerobot.com/{self.workspace}/v4'

    def _headers(self):
        return {'X-Filerobot-Key': self.api_key}

    def search(self, query=None, folder=None, filters=None, limit=100, offset=0):
        params = {'limit': limit, 'offset': offset}
        if query:
            params['name'] = query
        if folder:
            params['folder'] = folder
        if filters:
            params.update(filters)
        resp = requests.get(f'{self.base_url}/files', headers=self._headers(), params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def upload(self, filename, data, folder='/'):
        files = {'file': (filename, data)}
        params = {'folder': folder}
        resp = requests.post(
            f'{self.base_url}/files',
            headers=self._headers(),
            files=files,
            params=params,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def delete(self, file_uuid):
        resp = requests.delete(
            f'{self.base_url}/files/{file_uuid}',
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def get_file(self, file_uuid):
        resp = requests.get(
            f'{self.base_url}/files/{file_uuid}',
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def cdn_url(self, filename):
        return f'https://files.roxorgroup.com/{filename}'
