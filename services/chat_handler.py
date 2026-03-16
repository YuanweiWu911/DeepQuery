import os
import json
import requests
import asyncio
import re
from urllib.parse import urlparse
from .audio_util import AudioUtil
class ChatHandler:
    """Implements chat-specific business logic.
    
    Attributes:
        logger (logging.Logger): Configured logger instance
    """
 
    def __init__(self, logger):
        self.logger = logger
        self.audio_util = AudioUtil()
        self.is_voice_active = True

    # 添加新方法
    def set_voice_active(self, status: bool):
        """设置语音状态"""
        self.is_voice_active = status
        self.logger.info(f"[Chat] 语音状态已更新为: {status}")

    def web_search(self, prompt: str) -> str:
        """Performs web search using configured provider.
        
        Args:
            prompt (str): Search query text
            
        Returns:
            str: Formatted results or error message
            
        Raises:
            requests.RequestException: On network failures
            ValueError: On invalid API response
            
        Note:
            Reads provider and keys from config.WEB_SEARCH_CONFIG, with env fallback
        """
        try:
            provider, serper_key, bocha_key = self._resolve_web_search_provider()
            if provider in ("bocha", "bochaai"):
                return self._web_search_bocha(prompt, bocha_key)
            return self._web_search_serper(prompt, serper_key)
        except requests.RequestException as e:
            self.logger.error(f"[System] RequestException: {e}")
            return f"RequestException: {str(e)}"
        except ValueError as e:
            self.logger.error(f"[System] JSON error: {e}")
            return f"JSON error: {str(e)}"
        except Exception as e:
            self.logger.error(f"[System] Unknown error: {e}")
            return f"unknown error: {str(e)}"

    def _resolve_web_search_provider(self):
        try:
            from config import config as app_config
        except Exception:
            app_config = {}
        web_cfg = app_config.get("WEB_SEARCH_CONFIG", {}) if isinstance(app_config, dict) else {}
        provider = str(web_cfg.get("PROVIDER", "")).strip().lower()
        serper_key = str(web_cfg.get("SERPER_API_KEY", "")).strip() or os.getenv("SERPER_API_KEY", "")
        bocha_key = str(web_cfg.get("BOCHA_API_KEY", "")).strip() or os.getenv("BOCHA_API_KEY", "")
        if not provider:
            provider = "bocha" if bocha_key else "serper"
        return provider, serper_key.strip(), bocha_key.strip()

    def _web_search_serper(self, prompt: str, api_key: str) -> str:
        if not api_key:
            self.logger.error("[System] SERPER_API_KEY 未设置")
            return "未找到搜索结果"
        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json"
        }
        proxies = self._get_requests_proxies()
        response = self._requests_post(
            url="https://google.serper.dev/search",
            headers=headers,
            json_body={"q": prompt, "num": 20 if proxies else 10},
            proxies=proxies,
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("organic", [])[:10]
        if results:
            formatted_results = "\n\n".join(
                f"Title: {result.get('title', 'N/A')}\nLink: {result.get('link', 'N/A')}\nSnippet: {result.get('snippet', 'N/A')}"
                for result in results
            )
            return formatted_results
        return "未找到搜索结果"

    def _web_search_bocha(self, prompt: str, api_key: str) -> str:
        if not api_key:
            self.logger.error("[System] BOCHA_API_KEY 未设置")
            return "未找到搜索结果"
        url = os.getenv("BOCHA_API_URL", "").strip() or "https://api.bochaai.com/v1/web-search"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload_dict = {
            "query": prompt,
            "summary": True,
            "count": 10,
            "page": 1,
        }
        payload = json.dumps(payload_dict, ensure_ascii=False)
        session = requests.Session()
        session.trust_env = False
        try:
            proxies = self._get_requests_proxies()
            if proxies:
                try:
                    response = session.request("POST", url, headers=headers, data=payload, proxies=proxies, timeout=30)
                except requests.exceptions.ProxyError as e:
                    self.logger.warning(f"[System] ProxyError, retry without proxy: {e}")
                    response = session.request("POST", url, headers=headers, data=payload, timeout=30)
            else:
                response = session.request("POST", url, headers=headers, data=payload, timeout=30)
        finally:
            session.close()
        response.raise_for_status()
        raw = response.json()
        if isinstance(raw, dict):
            code = raw.get("code")
            if code is not None and str(code) != "200":
                msg = raw.get("msg") or raw.get("message") or "未找到搜索结果"
                self.logger.error(f"[System] Bocha API error: code={code}, msg={msg}")
                return str(msg)
            data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        else:
            data = {}

        web_pages = data.get("webPages", {}) if isinstance(data, dict) else {}
        items = web_pages.get("value", []) if isinstance(web_pages, dict) else []
        items = items[:10] if isinstance(items, list) else []
        if items:
            formatted_results = "\n\n".join(
                f"Title: {item.get('name', 'N/A')}\nLink: {item.get('url', 'N/A')}\nSnippet: {item.get('summary') or item.get('snippet') or 'N/A'}"
                for item in items
            )
            return formatted_results
        return "未找到搜索结果"

    def _requests_post(self, url: str, headers: dict, json_body: dict, proxies):
        session = requests.Session()
        session.trust_env = False
        try:
            if proxies:
                try:
                    return session.post(url, headers=headers, json=json_body, proxies=proxies, timeout=30)
                except requests.exceptions.ProxyError as e:
                    self.logger.warning(f"[System] ProxyError, retry without proxy: {e}")
                    return session.post(url, headers=headers, json=json_body, timeout=30)
            return session.post(url, headers=headers, json=json_body, timeout=30)
        finally:
            session.close()

    def _get_requests_proxies(self):
        proxy_url = os.getenv("PROXY_URL", "").strip()
        if not proxy_url:
            return None
        if "://" not in proxy_url:
            proxy_url = f"http://{proxy_url}"
        parsed = urlparse(proxy_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            self.logger.warning(f"[System] Ignore invalid PROXY_URL: {proxy_url}")
            return None
        if parsed.scheme == "https":
            proxy_url = f"http://{parsed.netloc}"
        return {
            "http": proxy_url,
            "https": proxy_url,
        }

    async def process_response(self, response_text):
        """处理响应并触发语音播放"""
        try:
            # 提取有效响应内容（移除<think>标签等内容）
            ai_response = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()
            self.logger.info(f"original ai_response: {ai_response}")
                        
            # 清理Markdown格式符号（增强版）
            markdown_patterns = [
                (r'#{1,6}\s*(.*)', r'\1'),        # 标题
                (r'\*\*([^*]+)\*\*', r'\1'),      # 加粗
                (r'\*([^*]+)\*', r'\1'),          # 斜体
                (r'`([^`]+)`', r'\1'),            # 内联代码
                (r'!\[.*?\]\(.*?\)', ''),         # 图片
                (r'\[.*?\]\(.*?\)', ''),          # 链接
                (r'-{3,}|={3,}', ''),             # 分割线
                (r'^\s*>\s*(.*)$', r'\1'),        # 引用
                (r'\|\|.*?\|\|', ''),             # 删除线
                (r'\s+', ' '),                    # 多个空格合并为一个
            ]
            
            for pattern, replacement in markdown_patterns:
                ai_response = re.sub(pattern, replacement, ai_response, flags=re.MULTILINE)
            self.logger.info(f"ai_response: {ai_response}")
            if ai_response and self.is_voice_active:
                # 调用语音合成播放
                asyncio.create_task(self.audio_util.say_response(ai_response))
            return ai_response
        except Exception as e:
            self.logger.error(f"响应处理失败: {str(e)}")
            return response_text
