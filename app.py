"""アニメ広報レポート自動生成ツール（SSEストリーミング対応）"""

import time
import re
import json
from datetime import datetime
from flask import Flask, render_template, request, Response, stream_with_context
from duckduckgo_search import DDGS

app = Flask(__name__)

MEDIA_MAP = {
    "natalie.mu": "コミックナタリー",
    "dengekionline.com": "電撃オンライン",
    "mantan-web.jp": "MANTANWEB",
    "anime.eiga.com": "アニメハック",
    "news.yahoo.co.jp": "Yahoo!ニュース",
    "animatetimes.com": "アニメイトタイムズ",
    "famitsu.com": "ファミ通.com",
    "4gamer.net": "4Gamer.net",
    "gigazine.net": "GIGAZINE",
    "nlab.itmedia.co.jp": "ねとらぼ",
    "oricon.co.jp": "ORICON NEWS",
    "realsound.jp": "リアルサウンド",
    "animeanime.jp": "アニメ!アニメ!",
    "eiga.com": "映画.com",
    "cinematoday.jp": "シネマトゥデイ",
    "jp.ign.com": "IGN Japan",
    "kai-you.net": "KAI-YOU",
    "game.watch.impress.co.jp": "GAME Watch",
    "hobby.watch.impress.co.jp": "HOBBY Watch",
    "av.watch.impress.co.jp": "AV Watch",
    "itmedia.co.jp": "ITmedia",
    "news.mynavi.jp": "マイナビニュース",
    "gamer.ne.jp": "Gamer",
    "comic-walker.com": "カドコミ",
    "manga.nicovideo.jp": "ニコニコ漫画",
    "koubo.jp": "Koubo",
    "news.toremaga.com": "とれまがニュース",
}

PR_DOMAINS = {
    "prtimes.jp": "PR TIMES",
    "atpress.ne.jp": "@Press",
    "valuepress.com": "ValuePress!",
}

SNS_DOMAINS = {"x.com", "twitter.com"}
INFO_DOMAINS = {"dic.pixiv.net", "ja.wikipedia.org", "anidb.net", "myanimelist.net"}


def get_domain(url):
    match = re.search(r'https?://(?:www\.)?([^/]+)', url)
    return match.group(1) if match else ""


def search_ddg(query, max_results=10, retries=2):
    for attempt in range(retries + 1):
        try:
            with DDGS() as ddgs:
                return list(ddgs.text(query, region="jp-jp", max_results=max_results))
        except Exception as e:
            if attempt < retries:
                time.sleep(3 * (attempt + 1))
    return []


def classify_result(url, title, body, anime_title):
    domain = get_domain(url)
    clean_anime = anime_title.replace(" ", "").replace("　", "")
    clean_title = title.replace(" ", "").replace("　", "")
    clean_body = body.replace(" ", "").replace("　", "")

    if clean_anime not in clean_title and clean_anime not in clean_body:
        return None, None

    for pr_domain, pr_name in PR_DOMAINS.items():
        if pr_domain in domain:
            return "press_release", {"source": pr_name, "title": title, "url": url, "body": body}

    if any(sns in domain for sns in SNS_DOMAINS):
        is_post = "/status/" in url
        account_match = re.search(r'(?:x\.com|twitter\.com)/(\w+)', url)
        account = f"@{account_match.group(1)}" if account_match else ""
        return "sns", {"account": account, "title": title, "url": url, "is_post": is_post, "body": body}

    if any(info in domain for info in INFO_DOMAINS):
        return "info", {"source": title, "url": url, "body": body}

    for media_domain, media_name in MEDIA_MAP.items():
        if media_domain in domain:
            return "media", {"media": media_name, "title": title, "url": url, "body": body}

    if any(kw in url for kw in ["/news/", "/article/", "/press/"]):
        return "media", {"media": domain, "title": title, "url": url, "body": body}

    # 既知カテゴリに該当しないが、アニメタイトルを含む関連ページ
    return "info", {"source": title, "url": url, "body": body}


def generate_report(anime_title, press_releases, media_coverage, sns_posts, info_pages):
    now = datetime.now().strftime("%Y年%m月%d日")
    lines = []
    lines.append(f"# 『{anime_title}』 広報レポート\n")
    lines.append(f"**作成日:** {now}")
    lines.append(f"**対象作品:** {anime_title}")
    lines.append("")
    lines.append("---\n")

    lines.append("## 1. プレスリリース\n")
    if press_releases:
        lines.append("| # | 配信元 | タイトル | URL |")
        lines.append("|---|--------|---------|-----|")
        for i, pr in enumerate(press_releases, 1):
            t = pr["title"][:60] + "..." if len(pr["title"]) > 60 else pr["title"]
            lines.append(f'| {i} | {pr["source"]} | {t} | {pr["url"]} |')
    else:
        lines.append("該当するプレスリリースは見つかりませんでした。\n")
    lines.append("")

    lines.append("---\n")
    lines.append("## 2. メディア掲載一覧\n")
    if media_coverage:
        lines.append("| # | メディア名 | 記事タイトル | URL |")
        lines.append("|---|----------|------------|-----|")
        for i, mc in enumerate(media_coverage, 1):
            t = mc["title"][:50] + "..." if len(mc["title"]) > 50 else mc["title"]
            lines.append(f'| {i} | {mc["media"]} | {t} | {mc["url"]} |')
        lines.append("")
        lines.append(f"**掲載メディア数: {len(set(mc['media'] for mc in media_coverage))}媒体 / 記事数: {len(media_coverage)}件**")
    else:
        lines.append("該当するメディア掲載は見つかりませんでした。\n")
    lines.append("")

    lines.append("---\n")
    lines.append("## 3. SNS（X / Twitter）\n")
    posts = [s for s in sns_posts if s["is_post"]]
    profiles = [s for s in sns_posts if not s["is_post"]]

    if posts:
        lines.append("### 関連投稿\n")
        lines.append("| # | アカウント | 内容 | URL |")
        lines.append("|---|----------|------|-----|")
        for i, p in enumerate(posts, 1):
            b = p["body"][:40] + "..." if len(p["body"]) > 40 else p["body"]
            lines.append(f'| {i} | {p["account"]} | {b} | {p["url"]} |')
    else:
        lines.append("関連投稿は検索で見つかりませんでした。\n")

    if profiles:
        lines.append("\n### 関連アカウント\n")
        for p in profiles:
            lines.append(f'- {p["account"]}: {p["url"]}')
    lines.append("")

    if info_pages:
        lines.append("---\n")
        lines.append("## 4. 関連情報ページ\n")
        for ip in info_pages:
            lines.append(f'- [{ip["source"]}]({ip["url"]})')
        lines.append("")

    lines.append("---\n")
    lines.append("## サマリー\n")
    lines.append(f"- プレスリリース: **{len(press_releases)}件**")
    mc_count = len(set(mc["media"] for mc in media_coverage)) if media_coverage else 0
    lines.append(f"- メディア掲載: **{mc_count}媒体 / {len(media_coverage)}記事**")
    lines.append(f"- SNS投稿: **{len(posts)}件**")
    lines.append(f"- 関連情報ページ: **{len(info_pages)}件**")
    lines.append("")

    lines.append("---\n")
    lines.append("## 注記\n")
    lines.append("- X（Twitter）のエンゲージメント数値（いいね・RT・インプレッション）はWeb検索では取得できません。")
    lines.append("- PR TIMESのPV数は管理画面からの確認が必要です。")
    lines.append("- 検索結果はDuckDuckGoのインデックスに依存しています。")
    lines.append("")
    lines.append("---\n")
    lines.append(f"*本レポートは自動検索により {now} に生成されました。*")

    return "\n".join(lines)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json()
    anime_title = data.get("title", "").strip()

    if not anime_title:
        return json.dumps({"error": "アニメタイトルを入力してください"}), 400

    def stream():
        press_releases, media_coverage, sns_posts, info_pages = [], [], [], []
        seen_urls = set()

        steps = [
            ("アニメ関連記事を検索中...", f'"{anime_title}" アニメ'),
            ("アニメ化ニュースを検索中...", f'"{anime_title}" アニメ化'),
            ("プレスリリースを検索中...", f'"{anime_title}" プレスリリース OR ニュース OR 発表'),
            ("SNS投稿を検索中...", f'{anime_title} site:x.com OR site:twitter.com'),
        ]

        for i, (label, query) in enumerate(steps):
            yield f"data: {json.dumps({'type': 'progress', 'step': i + 1, 'total': len(steps), 'message': label}, ensure_ascii=False)}\n\n"

            if i > 0:
                time.sleep(3)

            results = search_ddg(query, max_results=20)

            for r in results:
                url = r.get("href", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                category, item = classify_result(url, r.get("title", ""), r.get("body", ""), anime_title)
                if category == "press_release":
                    press_releases.append(item)
                elif category == "media":
                    media_coverage.append(item)
                elif category == "sns":
                    sns_posts.append(item)
                elif category == "info":
                    info_pages.append(item)

        yield f"data: {json.dumps({'type': 'progress', 'step': len(steps), 'total': len(steps), 'message': 'レポートを生成中...'}, ensure_ascii=False)}\n\n"

        report = generate_report(anime_title, press_releases, media_coverage, sns_posts, info_pages)

        yield f"data: {json.dumps({'type': 'done', 'report': report, 'stats': {'press_releases': len(press_releases), 'media_coverage': len(media_coverage), 'sns_posts': len([s for s in sns_posts if s['is_post']]), 'info_pages': len(info_pages)}}, ensure_ascii=False)}\n\n"

    return Response(stream_with_context(stream()), content_type="text/event-stream")


if __name__ == "__main__":
    app.run(debug=True, port=5001)
