"""Vercel Serverless Function: アニメコンテンツ生成API（Gemini API + SSE対応）
ツイートおよびプレスリリースの文章をGemini APIで生成する。
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

from google import genai


# ===== ログ =====
def log(msg):
    print(f"[content_generate] {msg}", flush=True)


# ===== 類例データ =====

EXAMPLE_TWEETS = [
    {
        "type": "放送情報",
        "text": """━━━━━━━━━━━━━
📺放送情報📺
━━━━━━━━━━━━━

TVアニメ『魔王武装のスレイブマスター』
2026年1月より放送開始！

🔹TOKYO MX：毎週金曜 24:00〜
🔹BS11：毎週金曜 24:30〜
🔹AT-X：毎週土曜 21:30〜

各配信プラットフォームでも順次配信予定！

🔗https://example.com/

#魔王武装 #maoumusou"""
    },
    {
        "type": "キャスト発表",
        "text": """🎉キャスト情報解禁🎉

TVアニメ『星降る夜のファミリア』
追加キャストを発表！

🌟リーナ・ヴァルトシュタイン役
 CV.水瀬いのり

🌟カイル・ブレイズ役
 CV.内田雄馬

ティザーPVも公開中▼
🔗https://example.com/pv

2026年4月放送開始！お楽しみに✨

#星ファミ #hoshifami"""
    },
    {
        "type": "イベント",
        "text": """【イベント開催決定！】

TVアニメ『ダンジョン飯』
スペシャルイベント
「冒険者たちの宴」開催決定🎊

📅2026年3月21日(土)
📍東京ガーデンシアター
🎤出演：熊谷健太郎、千本木彩花、泊明日菜 他

チケット最速先行は
BD&DVD第4巻封入抽選応募券にて！

▼詳細はこちら
🔗https://example.com/event

#ダンジョン飯"""
    },
]

EXAMPLE_PRESS_RELEASE = """
株式会社〇〇（本社：東京都渋谷区、代表取締役：〇〇）は、TVアニメ『〇〇〇〇』の第2期制作決定および2026年7月よりTOKYO MXほかにて放送開始することをお知らせいたします。あわせて、ティザービジュアルとティザーPVを公開いたしました。

■ティザービジュアル公開
本日解禁となったティザービジュアルでは、主人公〇〇が新たな装いで描かれており、第2期での新展開を予感させるものとなっています。

■スタッフ情報
監督：〇〇〇〇
シリーズ構成：〇〇〇〇
キャラクターデザイン：〇〇〇〇
アニメーション制作：〇〇スタジオ

■キャスト情報
〇〇〇〇 役：〇〇〇〇
〇〇〇〇 役：〇〇〇〇

■あらすじ
〇〇〇〇（作品の世界観とストーリーの概要）

■放送情報
TOKYO MX：2026年7月より毎週〇曜日 〇:〇〇〜
BS11：2026年7月より毎週〇曜日 〇:〇〇〜
各種配信プラットフォームにて順次配信予定

■関連イベント情報
（該当がある場合に記載）

■作品情報
原作：〇〇〇〇（〇〇社刊）
公式サイト：https://example.com/
公式X（Twitter）：@example_anime
公式ハッシュタグ：#〇〇〇〇
"""


# ===== プロンプト構築 =====

def build_tweet_prompt(form_data):
    examples_text = "\n\n".join(
        f"【{ex['type']}の例】\n{ex['text']}" for ex in EXAMPLE_TWEETS
    )

    tone_map = {
        "公式": "フォーマルで信頼感のあるトーン",
        "カジュアル": "親しみやすくフレンドリーなトーン",
        "盛り上げ": "ファンの期待感を煽るエモーショナルなトーン",
    }
    tone_desc = tone_map.get(form_data.get("tone", ""), "")

    user_parts = [f"作品タイトル: {form_data.get('title', '')}"]
    user_parts.append(f"告知内容: {form_data.get('announcement_type', '')}")
    user_parts.append(f"主要情報:\n{form_data.get('key_info', '')}")

    if form_data.get("hashtag"):
        user_parts.append(f"ハッシュタグ: {form_data['hashtag']}")
    if form_data.get("url"):
        user_parts.append(f"公式サイトURL: {form_data['url']}")
    if tone_desc:
        user_parts.append(f"トーン: {tone_desc}")

    prompt = f"""あなたはアニメ業界で10年以上の経験を持つ広報のプロフェッショナルです。
アニメ公式アカウントの告知ツイートを作成してください。

## ルール
- X（Twitter）の投稿として適切な長さ（280文字以内を目安）
- 装飾括弧【】『』を効果的に使用
- 絵文字を適度に使用してアイキャッチ効果を高める
- 罫線（━）やドット（・）で視認性を向上
- ハッシュタグは末尾にまとめる
- URLがある場合は見やすい位置に配置
- 改行を活用して読みやすくする

## 参考例
{examples_text}

## 入力情報
{chr(10).join(user_parts)}

## 出力
ツイート本文のみを出力してください。説明や前置きは不要です。"""

    return prompt


def build_press_release_prompt(form_data):
    user_parts = [f"作品タイトル: {form_data.get('title', '')}"]
    user_parts.append(f"見出し: {form_data.get('headline', '')}")
    user_parts.append(f"リード文の要点:\n{form_data.get('lead_summary', '')}")

    if form_data.get("staff_cast"):
        user_parts.append(f"スタッフ＆キャスト:\n{form_data['staff_cast']}")
    if form_data.get("synopsis"):
        user_parts.append(f"あらすじ:\n{form_data['synopsis']}")
    if form_data.get("visual_info"):
        user_parts.append(f"ビジュアル情報:\n{form_data['visual_info']}")
    if form_data.get("event_info"):
        user_parts.append(f"イベント・キャンペーン情報:\n{form_data['event_info']}")
    if form_data.get("source_material"):
        user_parts.append(f"原作情報: {form_data['source_material']}")
    if form_data.get("official_links"):
        user_parts.append(f"公式リンク・SNS:\n{form_data['official_links']}")

    prompt = f"""あなたはアニメ業界で10年以上の経験を持つ広報のプロフェッショナルです。
PR TIMES や @Press で配信するプレスリリースを作成してください。

## ルール
- ビジネス文書として適切なフォーマル日本語
- ただし読み手（メディア記者・ファン）に伝わりやすい表現
- 以下のセクション構成に従う:
  1. リード文（誰が・何を・いつ・どこで）
  2. ビジュアル公開情報（該当する場合）
  3. スタッフ＆キャスト情報
  4. あらすじ
  5. 放送・配信情報
  6. 関連イベント・キャンペーン情報（該当する場合）
  7. 原作・作品情報
  8. 公式サイト・SNS情報
- 各セクションは「■」で始まる見出しをつける
- 提供されていない情報のセクションは省略する
- 事実に基づいた内容のみ記載し、推測や創作は行わない

## 構成の参考例
{EXAMPLE_PRESS_RELEASE}

## 入力情報
{chr(10).join(user_parts)}

## 出力
プレスリリース本文のみを出力してください。説明や前置きは不要です。"""

    return prompt


def build_prompt(content_type, form_data):
    if content_type == "tweet":
        return build_tweet_prompt(form_data)
    elif content_type == "press_release":
        return build_press_release_prompt(form_data)
    else:
        raise ValueError(f"Unknown content_type: {content_type}")


# ===== Vercel Handler =====

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

        content_type = data.get("content_type", "").strip()
        form_data = data.get("form_data", {})

        if content_type not in ("tweet", "press_release"):
            self._send_json(400, {"error": "content_type は 'tweet' または 'press_release' を指定してください"})
            return

        if not form_data.get("title"):
            self._send_json(400, {"error": "作品タイトルを入力してください"})
            return

        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            self._send_json(500, {"error": "GEMINI_API_KEY が設定されていません"})
            return

        log(f"=== START: type={content_type} title='{form_data.get('title')}' ===")

        try:
            prompt = build_prompt(content_type, form_data)
        except ValueError as e:
            self._send_json(400, {"error": str(e)})
            return

        # SSEヘッダー送信
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        self._send_sse({"type": "progress", "message": "Gemini APIに接続中..."})

        try:
            client = genai.Client(api_key=api_key)

            full_text = ""
            response = client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            for chunk in response:
                if chunk.text:
                    full_text += chunk.text
                    self._send_sse({"type": "chunk", "text": chunk.text})

            self._send_sse({"type": "done", "full_text": full_text})
            log(f"=== DONE: {len(full_text)} chars generated ===")

        except Exception as e:
            log(f"Error: {e}")
            self._send_sse({"type": "error", "message": f"Gemini API エラー: {str(e)}"})

    def _send_sse(self, data):
        msg = f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        self.wfile.write(msg.encode("utf-8"))
        self.wfile.flush()

    def _send_json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
