"""Servidor do Leitor de Cupom Fiscal (NFC-e).

Serve o app (pasta static/) e expõe /api/nfce?url=<link do QR Code>, que busca a
página de consulta pública da SEFAZ e devolve os produtos em JSON. Sem dependências
externas: só a biblioteca padrão do Python.

Uso:  python server.py            (porta 8000)
      python server.py 8080
"""

import json
import os
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36"
)
MAX_BYTES = 3 * 1024 * 1024


# --------------------------------------------------------------------------- fetch

def is_allowed_host(url):
    """Só consultamos portais do governo, para o servidor não virar um proxy aberto."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return parts.scheme in ("http", "https") and (host.endswith(".gov.br") or host == "gov.br")


def fetch(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "pt-BR,pt;q=0.9",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=20)
    except urllib.error.URLError as e:
        # Vários portais estaduais têm cadeia de certificados incompleta.
        # Como só acessamos domínios .gov.br, tentamos de novo sem verificação.
        if not isinstance(getattr(e, "reason", None), ssl.SSLError):
            raise
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        resp = urllib.request.urlopen(req, timeout=20, context=ctx)

    with resp:
        raw = resp.read(MAX_BYTES)
        final_url = resp.geturl()
        charset = resp.headers.get_content_charset()

    if not charset:
        m = re.search(rb'charset=["\']?([\w-]+)', raw[:4000], re.I)
        charset = m.group(1).decode() if m else "utf-8"
    try:
        html = raw.decode(charset)
    except (LookupError, UnicodeDecodeError):
        html = raw.decode("latin-1")
    return html, final_url


# --------------------------------------------------------------------------- parse

class NfceHTMLParser(HTMLParser):
    """Coleta o texto de cada <tr> (linha mais interna) e de alguns elementos-chave."""

    CAPTURE = {"emitente": ("id", "u20"), "emitente2": ("class", "txtTopo")}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []          # [{"text": str, "spans": {class: text}}]
        self._row_stack = []
        self._span_classes = []
        self._captures = {}     # nome -> [tag, profundidade, texto]
        self.captured = {}
        self.iframes = []
        self.text_parts = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if tag == "tr":
            self._row_stack.append({"text": [], "spans": {}})
        elif tag == "iframe" and a.get("src"):
            self.iframes.append(a["src"])
        if tag == "span":
            self._span_classes.append(classes)
        if tag in ("br", "td", "th", "div", "p", "li"):
            self._add_text(" ")

        for name, cap in self._captures.items():
            if cap[0] == tag:
                cap[1] += 1
        for name, (attr, value) in self.CAPTURE.items():
            if name in self.captured or name in self._captures:
                continue
            if (attr == "id" and a.get("id") == value) or (attr == "class" and value in classes):
                self._captures[name] = [tag, 1, []]

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self._add_text(" ")
        elif tag == "iframe":
            src = dict(attrs).get("src")
            if src:
                self.iframes.append(src)

    def handle_endtag(self, tag):
        if tag == "tr" and self._row_stack:
            row = self._row_stack.pop()
            text = norm("".join(row["text"]))
            if text:
                self.rows.append({"text": text, "spans": {k: norm(v) for k, v in row["spans"].items()}})
        elif tag == "span" and self._span_classes:
            self._span_classes.pop()

        for name in list(self._captures):
            cap = self._captures[name]
            if cap[0] == tag:
                cap[1] -= 1
                if cap[1] == 0:
                    self.captured[name] = norm("".join(cap[2]))
                    del self._captures[name]

    def handle_data(self, data):
        self._add_text(data)
        if self._row_stack and self._span_classes:
            spans = self._row_stack[-1]["spans"]
            for cls in self._span_classes[-1]:
                spans[cls] = spans.get(cls, "") + data

    def _add_text(self, data):
        self.text_parts.append(data)
        if self._row_stack:
            self._row_stack[-1]["text"].append(data)
        for cap in self._captures.values():
            cap[2].append(data)


def norm(s):
    return re.sub(r"\s+", " ", unescape(s).replace("\xa0", " ")).strip()


def to_number(s):
    """'1.234,56' -> 1234.56 ; '1.0000' -> 1.0 ; '0,345' -> 0.345"""
    if s is None:
        return None
    s = s.strip().replace("R$", "").strip()
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


NUM = r"(\d[\d.]*(?:,\d+)?)"
RE_NAME = re.compile(r"^(.*?)\s*\(\s*C[óo]d(?:igo|\.)?\s*:?\s*([^)]*?)\s*\)", re.I)
RE_QTY = re.compile(r"Qtde?\.?(?:\s*total\s*de\s*[íi]tens)?\s*:?\s*" + NUM, re.I)
RE_UN = re.compile(r"\bUN\s*:\s*([A-Za-z0-9]{1,6})", re.I)
RE_UNIT = re.compile(r"V(?:l|alor)\.?\s*Unit(?:\.|[áa]rio)?\s*:?\s*(?:R\$)?\s*" + NUM, re.I)
RE_TOTAL = re.compile(r"V(?:l|alor)\.?\s*Total\s*(?:R\$)?\s*:?\s*(?:R\$)?\s*" + NUM, re.I)
RE_LAST_NUM = re.compile(r"(\d[\d.]*,\d{2})(?!.*\d)")


def parse_item(row):
    text = row["text"]
    m = RE_NAME.search(text)
    if not m or not RE_QTY.search(text):
        return None
    name = row["spans"].get("txtTit") or m.group(1)
    qty = to_number(RE_QTY.search(text).group(1))
    unit = RE_UN.search(text)
    unit_price = RE_UNIT.search(text)
    total = row["spans"].get("valor")
    if not total:
        mt = RE_TOTAL.search(text) or RE_LAST_NUM.search(text)
        total = mt.group(1) if mt else None
    total = to_number(total)
    unit_price = to_number(unit_price.group(1)) if unit_price else None
    if unit_price is None and total is not None and qty:
        unit_price = round(total / qty, 4)
    return {
        "nome": norm(name),
        "codigo": m.group(2).strip(),
        "quantidade": qty,
        "unidade": unit.group(1).upper() if unit else "",
        "valorUnitario": unit_price,
        "valorTotal": total,
    }


def parse_nfce(html):
    p = NfceHTMLParser()
    p.feed(html)
    p.close()

    items = []
    for row in p.rows:
        item = parse_item(row)
        if item and item["nome"]:
            items.append(item)

    full = norm("".join(p.text_parts))

    def find(pattern):
        m = re.search(pattern, full, re.I)
        return m.group(1) if m else None

    total = find(r"Valor\s+a\s+pagar\s*R?\$?\s*:?\s*" + NUM) or find(r"Valor\s+total\s*R?\$?\s*:?\s*" + NUM)
    desconto = find(r"Descontos?\s*R?\$?\s*:?\s*" + NUM)
    emitente = p.captured.get("emitente") or p.captured.get("emitente2") or ""
    return {
        "emitente": emitente,
        "cnpj": find(r"(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})") or "",
        "emissao": find(r"Emiss[ãa]o\s*:?\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}(?::\d{2})?)") or "",
        "itens": items,
        "total": to_number(total) if total else round(sum(i["valorTotal"] or 0 for i in items), 2),
        "desconto": to_number(desconto),
        "_iframes": p.iframes,
    }


def chave_from_url(url):
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    p = (q.get("p") or q.get("chNFe") or [""])[0]
    m = re.match(r"(\d{44})", p)
    return m.group(1) if m else ""


def consultar(url):
    html, final_url = fetch(url)
    data = parse_nfce(html)
    # Alguns estados (ex.: RS) mostram o cupom dentro de um iframe.
    if not data["itens"]:
        for src in data["_iframes"]:
            nested = urllib.parse.urljoin(final_url, src)
            if is_allowed_host(nested):
                data = parse_nfce(fetch(nested)[0])
                if data["itens"]:
                    break
    data.pop("_iframes", None)
    data["chave"] = chave_from_url(url)
    data["url"] = url
    return data


# --------------------------------------------------------------------------- http

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".webmanifest": "application/manifest+json",
        ".js": "text/javascript",
        ".svg": "image/svg+xml",
    }

    def do_GET(self):
        parts = urllib.parse.urlsplit(self.path)
        if parts.path == "/api/nfce":
            return self.api_nfce(parts.query)
        return super().do_GET()

    def end_headers(self):
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def api_nfce(self, query):
        url = (urllib.parse.parse_qs(query).get("url") or [""])[0].strip()
        if not is_allowed_host(url):
            return self.json(400, {"erro": "Esse QR Code não é de um cupom fiscal (NFC-e) da SEFAZ."})
        try:
            data = consultar(url)
        except Exception as e:  # noqa: BLE001 - qualquer falha vira mensagem para o usuário
            return self.json(502, {"erro": f"Não foi possível consultar a SEFAZ ({type(e).__name__}). Tente novamente.", "url": url})
        if not data["itens"]:
            return self.json(422, {
                "erro": "A SEFAZ respondeu, mas não encontrei produtos na página. "
                        "O cupom pode ainda não estar disponível ou o portal deste estado pede captcha.",
                "url": url,
            })
        return self.json(200, data)

    def json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def lan_ip():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 8000))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Leitor de Cupom rodando:")
    print(f"  neste PC:    http://localhost:{port}")
    print(f"  no celular:  http://{lan_ip()}:{port}  (mesma rede Wi-Fi)")
    print("Ctrl+C para parar.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
