"""Vercel Serverless Function: X Analytics CSVパース"""

import csv
import io
import json
from http.server import BaseHTTPRequestHandler


def parse_x_analytics_csv(csv_text):
    """X Analytics CSVをパースしてサマリーを返す"""
    reader = csv.DictReader(io.StringIO(csv_text))

    tweets = []
    total_impressions = 0
    total_engagements = 0
    total_retweets = 0
    total_replies = 0
    total_likes = 0
    total_url_clicks = 0
    total_media_views = 0

    for row in reader:
        try:
            impressions = float(row.get("impressions", 0) or 0)
            engagements = float(row.get("engagements", 0) or 0)
            retweets = float(row.get("retweets", 0) or 0)
            replies = float(row.get("replies", 0) or 0)
            likes = float(row.get("likes", 0) or 0)
            url_clicks = float(row.get("url clicks", 0) or 0)
            media_views_raw = row.get("media views", "0")
            media_views = float(media_views_raw) if media_views_raw not in ("-", "", None) else 0

            total_impressions += impressions
            total_engagements += engagements
            total_retweets += retweets
            total_replies += replies
            total_likes += likes
            total_url_clicks += url_clicks
            total_media_views += media_views

            tweet_text = row.get("Tweet text", "")
            tweet_url = row.get("Tweet permalink", "")
            tweet_time = row.get("time", "")

            tweets.append({
                "text": tweet_text[:80] + "..." if len(tweet_text) > 80 else tweet_text,
                "url": tweet_url,
                "time": tweet_time,
                "impressions": int(impressions),
                "engagements": int(engagements),
                "retweets": int(retweets),
                "replies": int(replies),
                "likes": int(likes),
                "url_clicks": int(url_clicks),
            })
        except (ValueError, TypeError):
            continue

    # いいね数でソート（トップツイート）
    tweets.sort(key=lambda t: t["likes"], reverse=True)

    tweet_count = len(tweets)
    avg_impressions = int(total_impressions / tweet_count) if tweet_count else 0
    avg_engagements = int(total_engagements / tweet_count) if tweet_count else 0
    eng_rate = (total_engagements / total_impressions * 100) if total_impressions else 0

    return {
        "summary": {
            "tweet_count": tweet_count,
            "total_impressions": int(total_impressions),
            "total_engagements": int(total_engagements),
            "total_retweets": int(total_retweets),
            "total_replies": int(total_replies),
            "total_likes": int(total_likes),
            "total_url_clicks": int(total_url_clicks),
            "total_media_views": int(total_media_views),
            "avg_impressions": avg_impressions,
            "avg_engagements": avg_engagements,
            "engagement_rate": round(eng_rate, 2),
        },
        "top_tweets": tweets[:10],
    }


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
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
