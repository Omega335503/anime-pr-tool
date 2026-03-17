"""アニメ広報レポート自動生成ツール"""

import time
import re
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from duckduckgo_search import DDGS

app = Flask(__name__)

# ドメイン→メディア名のマッピング
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
    "mynavinews.com": "マイナビニュース",
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
    """URLからドメインを抽出"""
    match = re.search(r'https?://(?:www\.)?([^/]+)', url)
    return match.group(1) if match else ""


def search_ddg(query, max_results=10, retries=3):
    """DuckDuckGoで検索（リトライ付き）"""
    for attempt in range(retries + 1):
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, region="jp-jp", max_results=max_results))
            return results
        except Exception as e:
            print(f"Search attempt {attempt + 1} failed for '{query}': {e}")
            if attempt < retries:
                wait = 5 * (attempt + 1)
                print(f"Waiting {wait}s before retry...")
                time.sleep(wait)
    return []


def classify_result(url, title, body, anime_title):
    """検索結果をカテゴリ別に分類"""
    domain = get_domain(url)
    clean_anime = anime_title.replace(" ", "").replace("　", "")

    # アニメタイトルとの関連性チェック
    clean_title = title.replace(" ", "").replace("　", "")
    clean_body = body.replace(" ", "").replace("　", "")
    is_relevant = clean_anime in clean_title or clean_anime in clean_body

    if not is_relevant:
        return None, None

    # プレスリリース
    for pr_domain, pr_name in PR_DOMAINS.items():
        if pr_domain in domain:
            return "press_release", {"source": pr_name, "title": title, "url": url, "body": body}

    # SNS
    if any(sns in domain for sns in SNS_DOMAINS):
        is_post = "/status/" in url
        account_match = re.search(r'(?:x\.com|twitter\.com)/(\w+)', url)
        account = f"@{account_match.group(1)}" if account_match else ""
        return "sns", {"account": account, "title": title, "url": url, "is_post": is_post, "body": body}

    # 情報ページ
    if any(info in domain for info in INFO_DOMAINS):
        return "info", {"source": title, "url": url, "body": body}

    # メディア掲載
    for media_domain, media_name in MEDIA_MAP.items():
        if media_domain in domain:
            return "media", {"media": media_name, "title": title, "url": url, "body": body}

    # 未知のニュースサイト（ドメインからメディア名を推定）
    if any(kw in url for kw in ["/news/", "/article/", "/press/"]):
        return "media", {"media": domain, "title": title, "url": url, "body": body}

    return None, None


def collect_all_results(anime_title):
    """少数の広い検索クエリで全カテゴリのデータを一括収集"""
    press_releases = []
    media_coverage = []
    sns_posts = []
    info_pages = []
    seen_urls = set()

    # 検索クエリリスト（少数に絞って、レート制限を回避）
    queries = [
        f'"{anime_title}" アニメ',
        f'"{anime_title}" アニメ化',
        f'"{anime_title}" プレスリリース OR ニュース OR 発表',
        f'{anime_title} site:x.com OR site:twitter.com',
    ]

    for i, query in enumerate(queries):
        if i > 0:
            time.sleep(5)  # レート制限対策（クエリ間5秒）
        results = search_ddg(query, max_results=25)

        for r in results:
            url = r.get("href", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = r.get("title", "")
            body = r.get("body", "")

            category, item = classify_result(url, title, body, anime_title)
            if category == "press_release":
                press_releases.append(item)
            elif category == "media":
                media_coverage.append(item)
            elif category == "sns":
                sns_posts.append(item)
            elif category == "info":
                info_pages.append(item)

    return press_releases, media_coverage, sns_posts, info_pages


def generate_report(anime_title, press_releases, media_coverage, sns_posts, info_pages):
    """Markdownレポートを生成"""
    now = datetime.now().strftime("%Y年%m月%d日")

    lines = []
    lines.append(f"# 『{anime_title}』 広報レポート\n")
    lines.append(f"**作成日:** {now}")
    lines.append(f"**対象作品:** {anime_title}")
    lines.append("")
    lines.append("---\n")

    # プレスリリース
    lines.append("## 1. プレスリリース\n")
    if press_releases:
        lines.append("| # | 配信元 | タイトル | URL |")
        lines.append("|---|--------|---------|-----|")
        for i, pr in enumerate(press_releases, 1):
            title_short = pr["title"][:60] + "..." if len(pr["title"]) > 60 else pr["title"]
            lines.append(f'| {i} | {pr["source"]} | {title_short} | {pr["url"]} |')
    else:
        lines.append("該当するプレスリリースは見つかりませんでした。\n")
    lines.append("")

    # メディア掲載
    lines.append("---\n")
    lines.append("## 2. メディア掲載一覧\n")
    if media_coverage:
        lines.append("| # | メディア名 | 記事タイトル | URL |")
        lines.append("|---|----------|------------|-----|")
        for i, mc in enumerate(media_coverage, 1):
            title_short = mc["title"][:50] + "..." if len(mc["title"]) > 50 else mc["title"]
            lines.append(f'| {i} | {mc["media"]} | {title_short} | {mc["url"]} |')
        lines.append("")
        lines.append(f"**掲載メディア数: {len(set(mc['media'] for mc in media_coverage))}媒体 / 記事数: {len(media_coverage)}件**")
    else:
        lines.append("該当するメディア掲載は見つかりませんでした。\n")
    lines.append("")

    # SNS
    lines.append("---\n")
    lines.append("## 3. SNS（X / Twitter）\n")
    posts = [s for s in sns_posts if s["is_post"]]
    profiles = [s for s in sns_posts if not s["is_post"]]

    if posts:
        lines.append("### 関連投稿\n")
        lines.append("| # | アカウント | 内容 | URL |")
        lines.append("|---|----------|------|-----|")
        for i, p in enumerate(posts, 1):
            body_short = p["body"][:40] + "..." if len(p["body"]) > 40 else p["body"]
            lines.append(f'| {i} | {p["account"]} | {body_short} | {p["url"]} |')
    else:
        lines.append("関連投稿は検索で見つかりませんでした。\n")

    if profiles:
        lines.append("\n### 関連アカウント\n")
        for p in profiles:
            lines.append(f'- {p["account"]}: {p["url"]}')
    lines.append("")

    # その他
    if info_pages:
        lines.append("---\n")
        lines.append("## 4. 関連情報ページ\n")
        for ip in info_pages:
            lines.append(f'- [{ip["source"]}]({ip["url"]})')
        lines.append("")

    # サマリー
    lines.append("---\n")
    lines.append("## サマリー\n")
    lines.append(f"- プレスリリース: **{len(press_releases)}件**")
    media_count = len(set(mc["media"] for mc in media_coverage)) if media_coverage else 0
    lines.append(f"- メディア掲載: **{media_count}媒体 / {len(media_coverage)}記事**")
    lines.append(f"- SNS投稿: **{len(posts)}件**")
    lines.append(f"- 関連情報ページ: **{len(info_pages)}件**")
    lines.append("")

    # 注記
    lines.append("---\n")
    lines.append("## 注記\n")
    lines.append("- X（Twitter）のエンゲージメント数値（いいね・RT・インプレッション）はWeb検索では取得できません。手動またはX API経由での確認が必要です。")
    lines.append("- PR TIMESのPV数は管理画面からの確認が必要です。")
    lines.append("- 各メディア記事のPV数は各メディアのレポート機能から確認してください。")
    lines.append("- 検索結果はDuckDuckGoのインデックスに依存しており、全ての記事を網羅できない場合があります。")
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
        return jsonify({"error": "アニメタイトルを入力してください"}), 400

    try:
        press_releases, media_coverage, sns_posts, info_pages = collect_all_results(anime_title)

        report = generate_report(anime_title, press_releases, media_coverage, sns_posts, info_pages)

        return jsonify({
            "report": report,
            "stats": {
                "press_releases": len(press_releases),
                "media_coverage": len(media_coverage),
                "sns_posts": len([s for s in sns_posts if s["is_post"]]),
                "info_pages": len(info_pages),
            }
        })
    except Exception as e:
        return jsonify({"error": f"検索中にエラーが発生しました: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5001)
