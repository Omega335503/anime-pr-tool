"""Google Docs/Sheets コンテンツ取得API（Google API版 - 高速）"""

import json
import re
import os
import time
from http.server import BaseHTTPRequestHandler

def log(msg):
    print(f"[fetch_gdoc] {msg}", flush=True)


def extract_doc_id(url):
    m = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
    return m.group(1) if m else None


def detect_doc_type(url):
    if 'docs.google.com/document' in url:
        return 'document'
    elif 'docs.google.com/spreadsheets' in url:
        return 'spreadsheet'
    return None


def fetch_google_doc(url):
    """Google Docs/Sheetsのコンテンツを取得（API優先、フォールバックあり）"""
    doc_id = extract_doc_id(url)
    if not doc_id:
        raise ValueError(f"Google Docs/Sheets URLからIDを抽出できません: {url}")

    doc_type = detect_doc_type(url)
    if not doc_type:
        raise ValueError(f"Google DocsまたはSheetsのURLを指定してください: {url}")

    # Google API キーを取得（Geminiと同じGCPプロジェクト）
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY", "")

    t0 = time.time()

    # まずGoogle APIで高速取得を試行
    try:
        if doc_type == 'spreadsheet':
            content = _fetch_sheets_api(doc_id, url, api_key)
        else:
            content = _fetch_docs_api(doc_id, api_key)
        log(f"[API] Fetched {len(content)} chars in {time.time()-t0:.2f}s")
        return {"doc_type": doc_type, "content": content, "doc_id": doc_id}
    except Exception as e:
        log(f"[API] Failed: {e}, falling back to export...")

    # フォールバック: export URL
    try:
        content = _fetch_export(doc_id, doc_type, url)
        log(f"[EXPORT] Fetched {len(content)} chars in {time.time()-t0:.2f}s")
        return {"doc_type": doc_type, "content": content, "doc_id": doc_id}
    except Exception as e:
        raise ValueError(f"取得に失敗しました: {e}")


_sheets_service = None

def _get_sheets_service(api_key):
    global _sheets_service
    if _sheets_service is None:
        from googleapiclient.discovery import build
        _sheets_service = build('sheets', 'v4', developerKey=api_key, cache_discovery=False)
    return _sheets_service


def _fetch_sheets_api(doc_id, url, api_key):
    """Google Sheets API v4 で直接データ取得（超高速）"""
    import requests as http_requests

    # gidからシート名を取得（軽量なREST直接呼び出し）
    gid_match = re.search(r'gid=(\d+)', url)
    target_gid = int(gid_match.group(1)) if gid_match else 0

    t0 = time.time()

    # メタ取得してgid→シート名変換（シート名がSheet1でないことが多い）
    meta_url = f"https://sheets.googleapis.com/v4/spreadsheets/{doc_id}?fields=sheets.properties&key={api_key}"
    r = http_requests.get(meta_url, timeout=5)
    meta = r.json()
    sheet_range = None
    for sheet in meta.get('sheets', []):
        props = sheet.get('properties', {})
        if props.get('sheetId', 0) == target_gid:
            sheet_range = props.get('title')
            break
    if not sheet_range and meta.get('sheets'):
        sheet_range = meta['sheets'][0]['properties']['title']
    if not sheet_range:
        sheet_range = 'Sheet1'
    log(f"[TIMING] sheets meta: {time.time()-t0:.2f}s, sheet={sheet_range}")

    # データ取得（REST直接呼び出し - discoveryのオーバーヘッドを回避）
    t1 = time.time()
    values_url = f"https://sheets.googleapis.com/v4/spreadsheets/{doc_id}/values/{sheet_range}?key={api_key}"
    r = http_requests.get(values_url, timeout=10)
    if r.status_code != 200:
        raise Exception(f"Sheets API error: {r.status_code} {r.text[:200]}")
    data = r.json()
    log(f"[TIMING] sheets values: {time.time()-t1:.2f}s")

    rows = data.get('values', [])
    if not rows:
        return ""

    lines = []
    max_cols = max(len(row) for row in rows) if rows else 0
    for row in rows:
        # 列数を揃える
        padded = list(row) + [''] * (max_cols - len(row))
        # ⚫︎（黒丸＋異体字セレクタ）を ● に正規化
        cells = [str(cell).replace('⚫︎', '●').replace('⚫', '●') for cell in padded]
        lines.append(','.join(cells))
    return '\n'.join(lines)


def _fetch_docs_api(doc_id, api_key):
    """Google Docs API v1 でプレーンテキスト取得（高速）"""
    from googleapiclient.discovery import build

    t0 = time.time()
    service = build('docs', 'v1', developerKey=api_key, cache_discovery=False)
    doc = service.documents().get(documentId=doc_id).execute()
    log(f"[TIMING] docs api: {time.time()-t0:.2f}s")

    # ドキュメントのBody要素からテキストを抽出
    content_parts = []
    for element in doc.get('body', {}).get('content', []):
        if 'paragraph' in element:
            for text_run in element['paragraph'].get('elements', []):
                text = text_run.get('textRun', {}).get('content', '')
                if text:
                    content_parts.append(text)
        elif 'table' in element:
            # テーブル処理
            for table_row in element['table'].get('tableRows', []):
                cells = []
                for cell in table_row.get('tableCells', []):
                    cell_text = ''
                    for cell_content in cell.get('content', []):
                        if 'paragraph' in cell_content:
                            for text_run in cell_content['paragraph'].get('elements', []):
                                cell_text += text_run.get('textRun', {}).get('content', '').strip()
                    cells.append(cell_text)
                content_parts.append('\t'.join(cells) + '\n')

    return ''.join(content_parts)


def _fetch_export(doc_id, doc_type, url):
    """フォールバック: export URL経由（複数方式で試行）"""
    import requests as http_requests

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/131.0.0.0 Safari/537.36",
    }

    if doc_type == 'document':
        export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
        r = http_requests.get(export_url, headers=headers, timeout=10, allow_redirects=True)
        if r.status_code == 200:
            r.encoding = 'utf-8'
            return r.text
        raise ValueError(f"HTTP {r.status_code}")

    # スプレッドシート: 複数方式で試行
    gid_match = re.search(r'gid=(\d+)', url)
    gid = gid_match.group(1) if gid_match else '0'

    # 方式1: 標準export URL
    export_url = f"https://docs.google.com/spreadsheets/d/{doc_id}/export?format=csv&gid={gid}"
    log(f"Export try 1: standard export")
    r = http_requests.get(export_url, headers=headers, timeout=10, allow_redirects=True)
    if r.status_code == 200:
        r.encoding = 'utf-8'
        return r.text
    log(f"Export try 1 failed: {r.status_code}")

    # 方式2: gviz endpoint（アップロードされたxlsxにも対応）
    gviz_url = f"https://docs.google.com/spreadsheets/d/{doc_id}/gviz/tq?tqx=out:csv&gid={gid}"
    log(f"Export try 2: gviz endpoint")
    r2 = http_requests.get(gviz_url, headers=headers, timeout=10, allow_redirects=True)
    if r2.status_code == 200:
        r2.encoding = 'utf-8'
        return r2.text
    log(f"Export try 2 failed: {r2.status_code}")

    # 方式3: Drive API（ネイティブSheets→CSV変換）
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    if api_key:
        drive_url = f"https://www.googleapis.com/drive/v3/files/{doc_id}/export?mimeType=text/csv&key={api_key}"
        log(f"Export try 3: Drive API export")
        r3 = http_requests.get(drive_url, timeout=10)
        if r3.status_code == 200:
            r3.encoding = 'utf-8'
            return r3.text
        log(f"Export try 3 failed: {r3.status_code}")

        # 方式4: Drive APIでxlsxを直接DL → メモリ内でCSV変換
        dl_url = f"https://www.googleapis.com/drive/v3/files/{doc_id}?alt=media&key={api_key}"
        log(f"Export try 4: Drive API raw download + xlsx parse")
        r4 = http_requests.get(dl_url, timeout=15)
        if r4.status_code == 200:
            return _parse_xlsx_bytes(r4.content)
        log(f"Export try 4 failed: {r4.status_code}")

    raise ValueError(f"全ての取得方式が失敗しました (最初のHTTPステータス: {r.status_code})")


def _parse_xlsx_bytes(data):
    """xlsxバイナリをCSV文字列に変換"""
    import io
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        lines = []
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) if c is not None else '' for c in row]
            lines.append(','.join(cells))
        wb.close()
        return '\n'.join(lines)
    except ImportError:
        # openpyxlがない場合、zipから直接xmlを読む簡易パーサー
        import zipfile
        import xml.etree.ElementTree as ET
        zf = zipfile.ZipFile(io.BytesIO(data))

        # shared strings
        shared = []
        if 'xl/sharedStrings.xml' in zf.namelist():
            ss_xml = ET.parse(zf.open('xl/sharedStrings.xml'))
            ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            for si in ss_xml.findall('.//s:si', ns):
                texts = si.findall('.//s:t', ns)
                shared.append(''.join(t.text or '' for t in texts))

        # sheet1
        sheet_xml = ET.parse(zf.open('xl/worksheets/sheet1.xml'))
        ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        lines = []
        for row_el in sheet_xml.findall('.//s:row', ns):
            cells = []
            for cell in row_el.findall('s:c', ns):
                v_el = cell.find('s:v', ns)
                val = ''
                if v_el is not None and v_el.text:
                    if cell.get('t') == 's':
                        idx = int(v_el.text)
                        val = shared[idx] if idx < len(shared) else ''
                    else:
                        val = v_el.text
                cells.append(val)
            lines.append(','.join(cells))
        zf.close()
        return '\n'.join(lines)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        from api.auth import require_auth
        auth_error = require_auth(self)
        if auth_error:
            self._send_json(auth_error[1], auth_error[0])
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON"})
            return

        url = data.get("url", "").strip()
        if not url:
            self._send_json(400, {"error": "URLを指定してください"})
            return

        try:
            result = fetch_google_doc(url)
            self._send_json(200, result)
        except ValueError as e:
            self._send_json(400, {"error": str(e)})
        except Exception as e:
            log(f"Error: {e}")
            self._send_json(500, {"error": f"取得エラー: {str(e)}"})

    def _send_json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
