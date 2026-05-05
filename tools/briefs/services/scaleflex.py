import os
import requests


class ScaleflexClient:
    def __init__(self):
        workspace = os.environ.get('SCALEFLEX_WORKSPACE', 'xa38qjmpah')
        self.base_url = os.environ.get('SCALEFLEX_API_URL', f'https://api.filerobot.com/{workspace}/v4/files')
        self.api_key = os.environ.get('SCALEFLEX_API_KEY', '')

    def upload_file(self, file_stream, filename, folder='/'):
        if not self.api_key:
            return {'error': 'No Scaleflex API key configured'}
        try:
            resp = requests.post(
                self.base_url,
                headers={'X-Filerobot-Key': self.api_key},
                files={'file': (filename, file_stream)},
                params={'folder': folder, 'overwrite': 'true'},
                timeout=120
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f'Scaleflex upload error: {e}')
            raise
