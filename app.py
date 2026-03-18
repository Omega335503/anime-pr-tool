"""アニメ広報レポート自動生成ツール（SSEストリーミング対応・ローカル開発用）"""

import time
import re
import json
from datetime import datetime
from urllib.parse import unquote
from flask import Flask, render_template, request, Response, stream_with_context
import requests as http_requests
from bs4 import BeautifulSoup

app = Flask(__name__)

# --- generate.py と同じロジック（ローカル開発用に同期） ---

MEDIA_MAP = {
    "natalie.mu": "コミックナタリー",
    "comic-natalie.com": "コミックナタリー",
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
    "koubo.jp": "Koubo",
    "news.toremaga.com": "とれまがニュース",
    "news.livedoor.com": "ライブドアニュース",
    "news.nifty.com": "ニフティニュース",
    "mdpr.jp": "モデルプレス",
    "excite.co.jp": "エキサイトニュース",
    "anime-recorder.com": "アニメレコーダー",
    "webnewtype.com": "WebNewtype",
    "febri.jp": "Febri",
    "lisani.jp": "リスアニ!",
    "nijimen.net": "にじめん",
    "hobby.dengeki.com": "電撃ホビーウェブ",
    "akiba-souken.com": "アキバ総研",
    "s-manga.net": "集英社マンガ",
    "websunday.net": "WEBサンデー",
    "bs4.jp": "BS日テレ",
    "ntv.co.jp": "日本テレビ",
}

PR_DOMAINS = {
    "prtimes.jp": "PR TIMES",
    "atpress.ne.jp": "@Press",
    "valuepress.com": "ValuePress!",
    "dreamnews.jp": "DreamNews",
}

SNS_DOMAINS = {"x.com", "twitter.com"}
INFO_DOMAINS = {"dic.pixiv.net", "ja.wikipedia.org", "anidb.net", "myanimelist.net",
                "anilist.co", "anime-planet.com", "annict.com"}
OFFICIAL_DOMAINS = {"anime.nicovideo.jp", "abema.tv", "tver.jp",
                    "netflix.com", "amazon.co.jp", "crunchyroll.com"}

SEARCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}


def log(msg):
    print(f"[generate] {msg}", flush=True)


def get_domain(url):
    match = re.search(r'https?://(?:www\.)?([^/]+)', url)
    return match.group(1) if match else ""


def search_startpage(query, max_results=12, retries=1):
    for attempt in range(retries + 1):
        try:
            r = http_requests.post(
                "https://www.startpage.com/sp/search",
                data={"query": query, "cat": "web", "language": "japanese"},
                headers=SEARCH_HEADERS,
                timeout=15,
            )
            log(f"Startpage [{query[:30]}...] status={r.status_code} len={len(r.text)}")
            if r.status_code != 200:
                raise Exception(f"Status {r.status_code}")

            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for el in soup.select(".result")[:max_results]:
                upper = el.select_one(".upper a[href^='http']")
                if not upper:
                    upper = el.select_one("a[href^='http']")
                if not upper:
                    continue
                url = upper.get("href", "")
                if "startpage.com" in url:
                    continue

                title_el = el.select_one("a.result-title")
                title = title_el.get_text(strip=True) if title_el else ""

                snippet_el = el.select_one("p.description") or el.select_one("p")
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                snippet = re.sub(r'^\d+\s*(?:日|時間|分|秒|週間|ヶ月)\s*前\.{3}\s*', '', snippet)

                if url and (title or snippet):
                    results.append({"href": url, "title": title, "body": snippet})

            log(f"  → {len(results)} results parsed")
            return results
        except Exception as e:
            log(f"Startpage attempt {attempt+1} failed: {e}")
            if attempt < retries:
                time.sleep(2)
    return []


def search_duckduckgo(query, retries=1):
    for attempt in range(retries + 1):
        try:
            r = http_requests.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query, "kl": "jp-jp"},
                headers=SEARCH_HEADERS,
                timeout=15,
            )
            log(f"DDG [{query[:30]}...] status={r.status_code}")
            if r.status_code != 200:
                raise Exception(f"Status {r.status_code}")
            soup = BeautifulSoup(r.text, "html.parser")
            if "captcha" in r.text.lower() or "bots use" in r.text.lower():
                log("  DDG CAPTCHA detected")
                return []
            results = []
            titles = soup.select(".result__a")
            snippets = soup.select(".result__snippet")
            for i, a_tag in enumerate(titles):
                href = a_tag.get("href", "")
                if "uddg=" in href:
                    match = re.search(r'uddg=([^&]+)', href)
                    if match:
                        href = unquote(match.group(1))
                title = a_tag.get_text(strip=True)
                body = snippets[i].get_text(strip=True) if i < len(snippets) else ""
                if href and title:
                    results.append({"href": href, "title": title, "body": body})
            log(f"  → {len(results)} results")
            return results
        except Exception as e:
            log(f"DDG attempt {attempt+1} failed: {e}")
            if attempt < retries:
                time.sleep(2)
    return []


def search_web(query, retries=1):
    results = search_startpage(query, retries=retries)
    if results:
        return results
    log("Startpage failed, trying DuckDuckGo fallback...")
    return search_duckduckgo(query, retries=retries)


def classify_result(url, title, body, anime_title):
    domain = get_domain(url)
    ws_re = re.compile(r'[\s\u3000\u00a0\u200b]+')
    clean_anime = ws_re.sub('', anime_title)
    clean_title = ws_re.sub('', title)
    clean_body = ws_re.sub('', body)
    clean_url = ws_re.sub('', unquote(url))

    if clean_anime not in clean_title and clean_anime not in clean_body and clean_anime not in clean_url:
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

    if any(kw in url for kw in ["/news/", "/article/", "/press/", "/topics/"]):
        return "media", {"media": domain, "title": title, "url": url, "body": body}

    if any(d in domain for d in OFFICIAL_DOMAINS):
        return "info", {"source": title, "url": url, "body": body}

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
    lines.append("- 検索結果はStartpage (Google) のインデックスに依存しています。")
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

    log(f"=== START: '{anime_title}' ===")

    def stream():
        press_releases, media_coverage, sns_posts, info_pages = [], [], [], []
        seen_urls = set()

        steps = [
            ("アニメ関連記事を検索中...",
             f'"{anime_title}" アニメ ニュース'),
            ("メディア掲載を検索中...",
             f'{anime_title} site:natalie.mu OR site:animeanime.jp OR site:oricon.co.jp OR site:mantan-web.jp OR site:animatetimes.com'),
            ("プレスリリースを検索中...",
             f'"{anime_title}" site:prtimes.jp OR site:atpress.ne.jp'),
            ("追加ニュースを検索中...",
             f'"{anime_title}" プレスリリース OR 発表 OR 放送'),
            ("SNS投稿を検索中...",
             f'{anime_title} site:x.com'),
        ]

        total_steps = len(steps) + 1

        for i, (label, query) in enumerate(steps):
            yield f"data: {json.dumps({'type': 'progress', 'step': i + 1, 'total': total_steps, 'message': label}, ensure_ascii=False)}\n\n"

            if i > 0:
                time.sleep(2)

            results = search_web(query)

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

        yield f"data: {json.dumps({'type': 'progress', 'step': total_steps, 'total': total_steps, 'message': 'レポートを生成中...'}, ensure_ascii=False)}\n\n"

        report = generate_report(anime_title, press_releases, media_coverage, sns_posts, info_pages)

        yield f"data: {json.dumps({'type': 'done', 'report': report, 'stats': {'press_releases': len(press_releases), 'media_coverage': len(media_coverage), 'sns_posts': len([s for s in sns_posts if s['is_post']]), 'info_pages': len(info_pages)}}, ensure_ascii=False)}\n\n"

        log(f"=== DONE: '{anime_title}' PR={len(press_releases)} Media={len(media_coverage)} SNS={len(sns_posts)} Info={len(info_pages)} ===")

    return Response(stream_with_context(stream()), content_type="text/event-stream")


if __name__ == "__main__":
    app.run(debug=True, port=5001)
