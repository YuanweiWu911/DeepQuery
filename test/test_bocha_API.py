import requests
import json
import os

url = "https://api.bochaai.com/v1/web-search"

payload = json.dumps({
  "query": "天空为什么是蓝色的？",
  "summary": True,
  "count": 10,
  "page": 1
})

headers = {
  'Authorization': f"Bearer {os.getenv('BOCHA_API_KEY', '')}",
  'Content-Type': 'application/json'
}

response = requests.request("POST", url, headers=headers, data=payload)

print(response.json())
