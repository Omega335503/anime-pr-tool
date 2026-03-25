"""Vercel Serverless Function: X Analytics CSVパース（日別・ツイート別 両対応）"""

import csv
import io
import json
from http.server import BaseHTTPRequestHandler


def safe_float(val):
    """安全に数値変換。'-'や空文字は0"""
    if val in ("-", "", None):
        return 0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0


def parse_account_overview(reader):
    """Account Overview CSV（日別データ）をパース"""
    days = []
    total_impressions = 0
    total_engagements = 0
    total_likes = 0
    total_reposts = 0
    total_replies = 0
    total_bookmarks = 0
    total_follows = 0
    total_profile_visits = 0
    total_video_views = 0

    for row in reader:
        impressions = safe_float(row.get("Impressions", 0))
        engagements = safe_float(row.get("Engagements", 0))
        likes = safe_float(row.get("Likes", 0))
        reposts = safe_float(row.get("Reposts", 0))
        replies = safe_float(row.get("Replies", 0))
        bookmarks = safe_float(row.get("Bookmarks", 0))
        follows = safe_float(row.get("New follows", 0))
        profile_visits = safe_float(row.get("Profile visits", 0))
        video_views = safe_float(row.get("Video views", 0))

        total_impressions += impressions
        total_engagements += engagements
        total_likes += likes
        total_reposts += reposts
        total_replies += replies
        total_bookmarks += bookmarks
        total_follows += follows
        total_profile_visits += profile_visits
        total_video_views += video_views

        days.append({
            "date": row.get("Date", ""),
            "impressions": int(impressions),
            "engagements": int(engagements),
            "likes": int(likes),
            "reposts": int(reposts),
        })

    days.sort(key=lambda d: d["impressions"], reverse=True)
    day_count = len(days)
    avg_impressions = int(total_impressions / day_count) if day_count else 0
    eng_rate = (total_engagements / total_impressions * 100) if total_impressions else 0

    return {
        "csv_type": "account_overview",
        "summary": {
            "tweet_count": day_count,
            "total_impressions": int(total_impressions),
            "total_engagements": int(total_engagements),
            "total_retweets": int(total_reposts),
            "total_replies": int(total_replies),
            "total_likes": int(total_likes),
            "total_url_clicks": int(total_bookmarks),
            "total_media_views": int(total_video_views),
            "avg_impressions": avg_impressions,
            "avg_engagements": int(total_engagements / day_count) if day_count else 0,
            "engagement_rate": round(eng_rate, 2),
            "total_follows": int(total_follows),
            "total_profile_visits": int(total_profile_visits),
        },
        "top_tweets": [
            {"text": d["date"], "url": "", "time": d["date"],
             "impressions": d["impressions"], "engagements": d["engagements"],
             "retweets": d["reposts"], "replies": 0, "likes": d["likes"], "url_clicks": 0}
            for d in days[:10]
        ],
    }


def parse_tweet_activity(reader):
    """Tweet Activity CSV（ツイート別データ）をパース"""
    tweets = []
    total_impressions = 0
    total_engagements = 0
    total_retweets = 0
    total_replies = 0
    total_likes = 0
    total_url_clicks = 0

    for row in reader:
        impressions = safe_float(row.get("impressions", 0))
        engagements = safe_float(row.get("engagements", 0))
        retweets = safe_float(row.get("retweets", 0))
        replies = safe_float(row.get("replies", 0))
        likes = safe_float(row.get("likes", 0))
        url_clicks = safe_float(row.get("url clicks", 0))

        total_impressions += impressions
        total_engagements += engagements
        total_retweets += retweets
        total_replies += replies
        total_likes += likes
        total_url_clicks += url_clicks

        tweet_text = row.get("Tweet text", "")
        tweets.append({
            "text": tweet_text[:80] + "..." if len(tweet_text) > 80 else tweet_text,
            "url": row.get("Tweet permalink", ""),
            "time": row.get("time", ""),
            "impressions": int(impressions),
            "engagements": int(engagements),
            "retweets": int(retweets),
            "replies": int(replies),
            "likes": int(likes),
            "url_clicks": int(url_clicks),
        })

    tweets.sort(key=lambda t: t["likes"], reverse=True)
    tweet_count = len(tweets)
    avg_impressions = int(total_impressions / tweet_count) if tweet_count else 0
    eng_rate = (total_engagements / total_impressions * 100) if total_impressions else 0

    return {
        "csv_type": "tweet_activity",
        "summary": {
            "tweet_count": tweet_count,
            "total_impressions": int(total_impressions),
            "total_engagements": int(total_engagements),
            "total_retweets": int(total_retweets),
            "total_replies": int(total_replies),
            "total_likes": int(total_likes),
            "total_url_clicks": int(total_url_clicks),
            "total_media_views": 0,
            "avg_impressions": avg_impressions,
            "avg_engagements": int(total_engagements / tweet_count) if tweet_count else 0,
            "engagement_rate": round(eng_rate, 2),
        },
        "top_tweets": tweets[:10],
    }


def parse_x_analytics_csv(csv_text):
    """CSV形式を自動判定してパース"""
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = reader.fieldnames or []

    if "Date" in fieldnames and "Impressions" in fieldnames:
        return parse_account_overview(reader)
    elif "Tweet id" in fieldnames or "impressions" in fieldnames:
        return parse_tweet_activity(reader)
    else:
        raise ValueError(f"不明なCSV形式です。カラム: {', '.join(fieldnames[:5])}")


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        from api.auth import require_auth
        auth_error = require_auth(self)
        if auth_error:
            self._send(auth_error[1], auth_error[0])
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._send(400, {"error": "Invalid JSON"})
            return

        csv_text = data.get("csv", "")
        if not csv_text:
            self._send(400, {"error": "CSVデータがありません"})
            return

        try:
            result = parse_x_analytics_csv(csv_text)
            self._send(200, result)
        except Exception as e:
            self._send(500, {"error": f"CSV解析エラー: {str(e)}"})

    def _send(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
