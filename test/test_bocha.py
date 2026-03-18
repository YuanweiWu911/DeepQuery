import requests
import json
import os

url = os.getenv("BOCHA_API_URL", "").strip() or "https://api.bochaai.com/v1/web-search"

payload = json.dumps({
  "query": "天空为什么是蓝色的？",
  "summary": True,
  "count": 10
})

api_key = os.getenv("BOCHA_API_KEY", "").strip()
if not api_key:
  try:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cfg = json.load(open(os.path.join(base_dir, "config.json"), "r", encoding="utf-8"))
    api_key = str((cfg.get("WEB_SEARCH_CONFIG", {}) or {}).get("BOCHA_API_KEY", "")).strip()
  except Exception:
    api_key = ""

headers = {
  "Authorization": f"Bearer {api_key}",
  "Content-Type": "application/json"
}

session = requests.Session()
session.trust_env = False
response = session.request("POST", url, headers=headers, data=payload, timeout=30)

print(response.json())
