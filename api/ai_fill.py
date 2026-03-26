from http.server import BaseHTTPRequestHandler
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.auth import require_auth_vercel

def get_gemini_client():
    from google import genai
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    return genai.Client(api_key=api_key)

def extract_json_from_response(text):
    text = text.strip()
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if m:
        text = m.group(1).strip()
    return json.loads(text)

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
        prompt = data.get("prompt", "")

        if not prompt:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "promptが空"}, ensure_ascii=False).encode())
            return

        try:
            client = get_gemini_client()
            response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            parsed = extract_json_from_response(response.text)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"fields": parsed}, ensure_ascii=False).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}, ensure_ascii=False).encode())
