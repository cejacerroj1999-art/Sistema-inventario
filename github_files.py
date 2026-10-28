"""Archivos privados: token exclusivamente en el proceso Python del servidor."""
import base64
import hashlib
from urllib.parse import quote
import requests


class GitHubFiles:
    def __init__(self, token, repo, branch):
        self.base = f'https://api.github.com/repos/{repo}/contents/'
        self.branch = branch
        self.session = requests.Session()
        self.session.headers.update({'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})

    def upload(self, file, kind):
        data = file.getvalue()
        if len(data) > 15 * 1024 * 1024:
            raise ValueError('Máximo 15 MB por documento')
        if data.startswith(b'%PDF-'):
            ext = 'pdf'
        elif data.startswith(b'\x89PNG\r\n\x1a\n'):
            ext = 'png'
        elif data.startswith(b'\xff\xd8\xff'):
            ext = 'jpg'
        else:
            raise ValueError('Sólo PDF, PNG o JPEG válidos')
        digest = hashlib.sha256(data).hexdigest()
        folder = 'Facturas' if kind == 'factura' else 'boletas'
        path = f'{folder}/{digest}.{ext}'
        url = self.base + quote(path, safe='/')
        existing = self.session.get(url, params={'ref': self.branch}, timeout=30)
        if existing.status_code == 200:
            obj = existing.json()
            return dict(archivo_path=path, archivo_url=obj['html_url'], archivo_sha=obj['sha'])
        if existing.status_code != 404:
            raise RuntimeError(f'GitHub consulta: HTTP {existing.status_code}')
        for _ in range(3):
            response = self.session.put(url, json={'message': f'Archivo {kind} {digest[:12]}',
                'content': base64.b64encode(data).decode(), 'branch': self.branch}, timeout=45)
            if response.status_code in (200, 201):
                obj = response.json()['content']
                return dict(archivo_path=path, archivo_url=obj['html_url'], archivo_sha=obj['sha'])
            if response.status_code not in (409, 422):
                break
            # Otro proceso pudo subir exactamente el mismo archivo.
            r = self.session.get(url, params={'ref': self.branch}, timeout=30)
            if r.status_code == 200:
                obj = r.json()
                return dict(archivo_path=path, archivo_url=obj['html_url'], archivo_sha=obj['sha'])
        raise RuntimeError(f'GitHub carga: HTTP {response.status_code}; reintente')

    def download(self, path, sha):
        # Leer el blob concreto, aunque el archivo haya cambiado en la rama.
        repo_base = self.base.removesuffix('contents/')
        response = self.session.get(repo_base + 'git/blobs/' + quote(sha, safe=''), timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f'GitHub descarga: HTTP {response.status_code}')
        return base64.b64decode(response.json()['content'])
