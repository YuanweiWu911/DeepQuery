import json
import os

import requests


def main():
    api_key = os.getenv("BOCHA_API_KEY", "")
    if not api_key:
        raise RuntimeError("BOCHA_API_KEY 未设置")

    url = "https://api.bochaai.com/v1/web-search"
    payload = json.dumps(
        {
            "query": "天空为什么是蓝色的？",
            "summary": True,
            "count": 10,
            "page": 1,
        }
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = requests.request("POST", url, headers=headers, data=payload, timeout=30)
    response.raise_for_status()
    print(response.json())


if __name__ == "__main__":
    main()
