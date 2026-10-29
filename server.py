import json
import os
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from html import escape
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Compatibilidade com sua pasta "estático" e também "static"
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "estático"
if not STATIC_DIR.exists():
    STATIC_DIR = BASE_DIR / "estatico"
if not STATIC_DIR.exists():
    STATIC_DIR = BASE_DIR / "static"
    if not STATIC_DIR.exists():
        STATIC_DIR = BASE_DIR

USER_AGENT = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36"
MAX_BYTES = 3 * 1024 * 1024

class NFCEParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.produtos = []
        self.total = None
        self.cnpj = None
        self.nome_loja = None
        self._in_prod = False
        self._current = {}

    def handle_data(self, data):
        d = data.strip()
        if not d:
            return
        # Lógica simples para pegar itens da SEFAZ
        if re.search(r"\d+,\d{2}", d):
            pass

def fetch_nfce(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
            html = r.read(MAX_BYTES).decode('utf-8', errors='ignore')
            return html
    except Exception as e:
        return f"ERRO: {e}"

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/nfce":
            qs = urllib.parse.parse_qs(parsed.query)
            url = qs.get("url", [None])[0]
            if not url:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"erro": "url obrigatoria"}).encode())
                return
            html = fetch_nfce(url)
            # Parser muito simplificado - ajuste conforme seu original
            # Aqui retorna o HTML para o front fazer o parse
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"html": html[:20000]}).encode())
            return
        return super().do_GET()

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", os.environ.get("PORTA", 8000)))
    print(f"Iniciando na porta {port} servindo {STATIC_DIR}")
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
