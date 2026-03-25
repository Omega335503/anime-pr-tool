"""Vercel Serverless Function: Geminiで資料を個別に構造化整形"""

import json
import os
from http.server import BaseHTTPRequestHandler
from google import genai


def log(msg):
    print(f"[extract_info] {msg}", flush=True)


# ===== 資料ごとの個別プロンプト =====

TIMELINE_PROMPT = """あなたはアニメ業界の広報アシスタントです。
以下は「宣伝タイムライン」の資料です。入れ子構造のJSONに変換してください。

## 出力JSON形式
```json
[
  {
    "date": "11/24",
    "title": "キャスト確定",
    "category": "制作進行",
    "items": [
      {
        "label": "大項目テキスト",
        "children": [
          "小項目テキスト1",
          "小項目テキスト2"
        ]
      }
    ]
  }
]
```

## categoryの分類ルール（必ず以下のいずれかを設定すること）
- "MTG" … 会議・ミーティング・打ち合わせの議事録・決定事項
- "プレスリリース" … PR TIMES等でのプレスリリース配信
- "X更新" … X(Twitter)での投稿・告知ツイート
- "PV/映像" … PV・ティザー・CM等の映像公開
- "Web/HP" … 公式サイト更新・HP公開
- "イベント" … リアルイベント・先行上映会・ステージ
- "制作進行" … アフレコ・納品・制作マイルストーン
- "メディア" … メディア取材・インタビュー・雑誌掲載
- "コラボ/グッズ" … コラボ・グッズ・タイアップ
- "その他" … 上記に該当しないもの

## ルール
- 資料に書かれている情報をそのまま使うこと（勝手に言い換えない）
- 日付がある項目は日付順に並べる
- 1つの日付エントリに対して、その下の箇条書きをitemsとして格納
- items内のlabelは大項目、childrenは小項目（インデントされた内容）
- childrenがなければ空配列 []
- 日付が不明な項目は date を "日付未定" とする
- 情報の追加・削除・改変は一切行わないこと
- 内容からcategoryを判定すること（複数該当する場合は最も主要なもの1つ）

## 資料
```
{content}
```

## 出力
上記JSON形式のみを出力。説明や前置きは不要。```json で囲むこと。"""

TEXT_MASTER_PROMPT = """あなたはアニメ業界の広報アシスタントです。
以下は「テキストマスター」の資料（CSV/表形式）です。表構造を維持したJSONに変換してください。

## 重要：解禁タイミングの仕組み
この表には「●」マークの列があります。これは情報の解禁タイミングを示します。
- 列ヘッダーが日付や施策名（例: "5/8", "7月HP", "9月PV2", "10月1話"）
- セルが「●」= その時点で解禁される情報
- セルが空 = まだ非公開

## 出力JSON形式
```json
{
  "headers": ["カラム1", "カラム2", "解禁1", "解禁2"],
  "release_columns": [2, 3],
  "sections": [
    {
      "title": "セクション名（あれば）",
      "rows": [
        ["セル1", "セル2", "●", ""],
        ["セル1", "セル2", "", "●"]
      ]
    }
  ]
}
```

## ルール
- 元CSVのカラム構造をそのまま維持する
- headersには元データの列ヘッダーをそのまま使う（最初の行をヘッダーとする）
- 意味のない区切り列（「：」や「:」だけの列など）は除外する
- release_columns: 「●」が入る解禁タイミング列のインデックス（0始まり）の配列。ヘッダーに日付や施策名が入っている列を指定
- **セクション分割は必須**: 空行やカテゴリ名だけの行（例:「スタッフ」「キャスト」等）を見つけたら、それをセクションのtitleにする。最初のセクション（作品名など）にもtitleを付けること（例:「作品表記」）
- すべてのデータ行がいずれかのsectionに属すること
- 空セルは空文字 "" にする
- 「●」はそのまま「●」として出力すること（絶対に変換・削除しない）
- 元データに「●」がある箇所は**必ず**「●」を出力する。○に変えない
- 情報の追加・削除・改変は一切行わないこと
- 元データにない情報を推測・補完しない

## 資料
```
{content}
```

## 出力
上記JSON形式のみを出力。説明や前置きは不要。```json で囲むこと。"""

BUDGET_PROMPT = """あなたはアニメ業界の広報アシスタントです。
以下は「宣伝予算表」の資料（CSV/表形式）です。表構造を維持したJSONに変換してください。

## 出力JSON形式
```json
{
  "headers": ["カラム1", "カラム2", "カラム3"],
  "sections": [
    {
      "title": "カテゴリ名",
      "rows": [
        ["項目名", "金額", "備考"],
        ["小計", "合計金額", ""]
      ]
    }
  ]
}
```

## ルール
- 元CSVのカラム構造をそのまま維持する
- headersには元データの列ヘッダーをそのまま使う
- カテゴリ分けがあればsectionsに分割
- 金額はそのまま記載（勝手にフォーマットを変えない）
- 空セルは空文字 "" にする
- 情報の追加・削除・改変は一切行わないこと

## 資料
```
{content}
```

## 出力
上記フォーマットで整形した結果のみを出力してください。説明や前置きは不要です。"""

# 基本情報抽出用（作品タイトル・ハッシュタグ等の最小限）
META_PROMPT = """以下の資料群からアニメ作品の基本メタ情報のみをJSON形式で抽出してください。

## ルール
- 資料に明記されている情報のみ（推測・創作は行わない）
- 該当しない場合は空文字 ""

## 出力JSON
```json
{
  "title": "作品タイトル",
  "hashtags": "#ハッシュタグ",
  "official_url": "公式サイトURL",
  "official_x": "@公式Xアカウント"
}
```

## 資料
{content}

JSONのみ出力。"""

PROMPTS = {
    "timeline": TIMELINE_PROMPT,
    "text_master": TEXT_MASTER_PROMPT,
    "budget": BUDGET_PROMPT,
}

DOC_LABELS = {
    "timeline": "宣伝タイムライン",
    "text_master": "テキストマスター",
    "budget": "宣伝予算表",
}


def build_individual_prompt(doc_type, content):
    """資料タイプに応じた個別プロンプトを構築"""
    template = PROMPTS.get(doc_type, "")
    if not template:
        return None
    return template.replace("{content}", content[:10000])


def build_meta_prompt(documents):
    """基本メタ情報抽出用プロンプト"""
    parts = []
    for key, label in DOC_LABELS.items():
        doc = documents.get(key)
        if doc and doc.get("content"):
            parts.append(f"### {label}\n{doc['content'][:3000]}")
    return META_PROMPT.replace("{content}", "\n".join(parts))


def extract_json_from_response(text):
    """Geminiの応答からJSONを抽出"""
    import re
    m = re.search(r'```json\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    return json.loads(text)


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

        documents = data.get("documents", {})
        if not any(documents.get(k, {}).get("content") for k in ("timeline", "text_master", "budget")):
            self._send_json(400, {"error": "少なくとも1つの資料が必要です"})
            return

        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            self._send_json(500, {"error": "GEMINI_API_KEY が設定されていません"})
            return

        log(f"=== EXTRACT START ===")

        try:
            client = genai.Client(api_key=api_key)
            structured = {}

            # 各資料を個別に構造化
            for doc_type in ("timeline", "text_master", "budget"):
                doc = documents.get(doc_type)
                if not doc or not doc.get("content"):
                    continue

                prompt = build_individual_prompt(doc_type, doc["content"])
                if not prompt:
                    continue

                log(f"Structuring {doc_type}... ({len(doc['content'])} chars)")
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                )
                structured[doc_type] = response.text.strip()
                log(f"  → {len(structured[doc_type])} chars")

            # 基本メタ情報を抽出（タイトル・ハッシュタグ等）
            log("Extracting meta...")
            meta_prompt = build_meta_prompt(documents)
            meta_response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=meta_prompt,
            )
            try:
                meta = extract_json_from_response(meta_response.text)
            except (json.JSONDecodeError, Exception):
                meta = {"title": "", "hashtags": "", "official_url": "", "official_x": ""}

            log(f"=== EXTRACT DONE: title={meta.get('title', '?')} ===")

            self._send_json(200, {
                "extracted": meta,
                "structured": structured,
            })

        except Exception as e:
            log(f"Error: {e}")
            self._send_json(500, {"error": f"抽出エラー: {str(e)}"})

    def _send_json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
