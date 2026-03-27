from http.server import BaseHTTPRequestHandler
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.extract_info import build_individual_prompt
from api.auth import require_auth_vercel

def get_gemini_client():
    from google import genai
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    return genai.Client(api_key=api_key)

def extract_json_from_response(text):
    import re
    text = text.strip()
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if m:
        text = m.group(1).strip()
    return json.loads(text)

def parse_csv_to_table(csv_text):
    import csv, io
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return {"headers": [], "sections": [], "release_columns": []}
    header_row = rows[0]
    release_cols = []
    for ci, cell in enumerate(header_row):
        if ci >= 2 and cell.strip():
            release_cols.append(ci)
    sections = []
    current_section = {"title": "作品情報", "rows": []}
    SECTION_KEYWORDS = {"スタッフ", "キャスト", "楽曲", "主題歌", "放送", "配信", "SNS", "X", "制作物", "映像", "PV", "その他"}
    for ri, row in enumerate(rows[1:], 1):
        if not any(cell.strip() for cell in row):
            continue
        first = (row[0] if row else "").strip().replace("：", "").replace(":", "")
        if first and not any(c.strip() for c in row[1:]) and any(kw in first for kw in SECTION_KEYWORDS):
            if current_section["rows"]:
                sections.append(current_section)
            current_section = {"title": first, "rows": []}
            continue
        cleaned = []
        skip_colon = False
        for ci, cell in enumerate(row):
            c = cell.strip().replace("⚫︎", "●").replace("⚫", "●")
            if ci == 1 and c in ("：", ":"):
                skip_colon = True
                continue
            if skip_colon and ci == 1:
                continue
            cleaned.append(c)
        if any(c for c in cleaned):
            while len(cleaned) < len(header_row) - (1 if skip_colon else 0):
                cleaned.append("")
            current_section["rows"].append(cleaned)
    if current_section["rows"]:
        sections.append(current_section)
    clean_headers = [h for i, h in enumerate(header_row) if i != 1 or not any(r[1].strip() in ("：", ":") for r in rows[1:3] if len(r) > 1)]
    return {"headers": clean_headers, "sections": sections, "release_columns": release_cols}

def structure_budget(content, get_client_fn, extract_json_fn):
    """宣伝予算表をAIで構造化"""
    prompt = f"""以下はアニメ作品の宣伝予算表（CSV/テーブルデータ）です。
これを以下のJSON形式に構造化してください。

## 出力フォーマット（厳密に従ってください）
```json
{{
  "items": [
    {{
      "category": "科目（MTG/プレスリリース/SNS更新/制作物/WEB/HP/イベント/アニメ制作/メディア/コラボ/グッズ/その他）",
      "billing_month": "請求月（例: 2026/04）",
      "vendor": "発注先",
      "description": "宣伝内容",
      "period": "実施時期",
      "estimate": "見込み額（税抜）数値のみ",
      "actual": "実施金額（税抜）数値のみ、未確定なら空文字",
      "is_must": true,
      "note": "補足"
    }}
  ],
  "summary": {{
    "total_budget": "宣伝予算総額（数値）",
    "must_total": "マスト費用合計（数値）",
    "option_total": "オプション費用合計（数値）",
    "must_option_total": "マスト+オプション合計（数値）",
    "remaining": "残額（数値）"
  }}
}}
```

## ルール
- is_must: マスト施策ならtrue、オプションならfalse。判断できない場合はtrue
- 金額は数値のみ（カンマ・円記号は除去）。不明なら0
- 空行・合計行・ヘッダー行はitemsに含めない
- summaryは元データに記載があればそのまま、なければitemsから計算

## 元データ
{content}"""

    client = get_client_fn()
    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    try:
        parsed = extract_json_fn(response.text)
        return parsed
    except:
        return {"items": [], "summary": {}, "raw": response.text.strip()}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        auth_err = require_auth_vercel(self)
        if auth_err:
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(auth_err, ensure_ascii=False).encode())
            return

        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length)) if length else {}
        doc_type = data.get("doc_type", "")
        content = data.get("content", "")
        instructions = data.get("instructions", "")

        if doc_type not in ("timeline", "text_master", "budget"):
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "無効なdoc_type"}, ensure_ascii=False).encode())
            return

        try:
            if doc_type == "budget":
                parsed = structure_budget(content, get_gemini_client, extract_json_from_response)
                result = {"structured": parsed}
            elif doc_type == "text_master":
                parsed = parse_csv_to_table(content)
                result = {"structured": parsed}
            else:
                prompt = build_individual_prompt(doc_type, content)
                if instructions:
                    prompt += f"\n\n## ユーザーからの追加指示（必ず従うこと）\n{instructions}"
                client = get_gemini_client()
                response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
                try:
                    parsed = extract_json_from_response(response.text)
                    result = {"structured": parsed}
                except:
                    result = {"structured": response.text.strip()}

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}, ensure_ascii=False).encode())
