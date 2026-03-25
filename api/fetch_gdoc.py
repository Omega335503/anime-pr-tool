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
    """フォールバック: export URL経由（遅い）"""
    import requests as http_requests

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/131.0.0.0 Safari/537.36",
    }

    if doc_type == 'document':
        export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    else:
        gid_match = re.search(r'gid=(\d+)', url)
        gid = gid_match.group(1) if gid_match else '0'
        export_url = f"https://docs.google.com/spreadsheets/d/{doc_id}/export?format=csv&gid={gid}"

    log(f"Export fallback: {export_url}")
    r = http_requests.get(export_url, headers=headers, timeout=10, allow_redirects=True)

    if r.status_code == 404:
        raise ValueError("ドキュメントが見つかりません")
    elif r.status_code in (401, 403):
        raise ValueError("アクセス拒否。共有設定を確認してください")
    elif r.status_code != 200:
        raise ValueError(f"HTTP {r.status_code}")

    r.encoding = 'utf-8'
    return r.text


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
