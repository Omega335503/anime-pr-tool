"""Google OAuth トークン検証モジュール（高速キャッシュ版）"""

import json
import time
import base64

GOOGLE_CLIENT_ID = "105287262948-9qob3e7bv0aaeqk92ou40mmlqtnsp1u0.apps.googleusercontent.com"

# 検証済みトークンキャッシュ {token_hash: {user, expires}}
_token_cache = {}


def _base64url_decode(s):
    s += '=' * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


def _decode_jwt(token):
    """JWTペイロードをデコード"""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        payload = json.loads(_base64url_decode(parts[1]))
        return payload
    except Exception:
        return None


def verify_google_token(token):
    """
    Google ID トークンを検証する（キャッシュ付き高速版）
    初回はJWTデコード+基本検証、以降はキャッシュから返す
    """
    if not token:
        return None

    # キャッシュチェック（トークンの先頭50文字をキーに）
    cache_key = token[:50]
    cached = _token_cache.get(cache_key)
    if cached and cached["expires"] > time.time():
        return cached["user"]

    # JWTをローカルでデコード（Google APIを呼ばない）
    payload = _decode_jwt(token)
    if not payload:
        return None

    # クライアントID確認
    if payload.get("aud") != GOOGLE_CLIENT_ID:
        return None

    # 発行者確認
    iss = payload.get("iss", "")
    if iss not in ("accounts.google.com", "https://accounts.google.com"):
        return None

    # 有効期限チェック
    exp = int(payload.get("exp", 0))
    if exp < time.time():
        return None

    user = {
        "email": payload.get("email"),
        "name": payload.get("name"),
        "picture": payload.get("picture"),
        "sub": payload.get("sub"),
    }

    # キャッシュに保存（トークンの有効期限まで）
    _token_cache[cache_key] = {"user": user, "expires": exp}

    # 古いキャッシュを掃除（100件超えたら）
    if len(_token_cache) > 100:
        now = time.time()
        expired = [k for k, v in _token_cache.items() if v["expires"] < now]
        for k in expired:
            del _token_cache[k]

    return user


def require_auth(request_obj):
    """
    Flask/Vercel リクエストから認証トークンを検証。
    認証失敗時は (error_dict, status_code) を返す。
    成功時は None を返す。
    """
    auth_header = None

    if hasattr(request_obj, 'headers'):
        headers = request_obj.headers
        if hasattr(headers, 'get'):
            auth_header = headers.get("Authorization", "") or ""
        else:
            auth_header = ""

    if not auth_header or not auth_header.startswith("Bearer "):
        return {"error": "認証が必要です。ログインしてください。"}, 401

    token = auth_header[7:]
    user = verify_google_token(token)

    if not user:
        return {"error": "認証トークンが無効です。再ログインしてください。"}, 401

    return None
