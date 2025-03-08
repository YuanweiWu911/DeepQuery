import os
import requests
import asyncio
import re
from .audio_util import AudioUtil
class ChatHandler:
    """Implements chat-specific business logic.
    
    Attributes:
        logger (logging.Logger): Configured logger instance
    """
 
    def __init__(self, logger):
        self.logger = logger
        self.audio_util = AudioUtil()

    def web_search(self, prompt: str) -> str:
        """Performs web search using Google Serper API.
        
        Args:
            prompt (str): Search query text
            
        Returns:
            str: Formatted results or error message
            
        Raises:
            requests.RequestException: On network failures
            ValueError: On invalid API response
            
        Note:
            Requires SERPER_API_KEY environment variable
        """

        api_key = os.getenv("SERPER_API_KEY")
        if api_key is None:
            self.logger.error("[System] SERPER_API_KEY 未设置")
            return "未找到搜索结果"
        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json"
        }
        proxy_url = os.getenv("PROXY_URL")
        try:
            if proxy_url:
                proxies = {
                    "http": proxy_url,
                    "https": proxy_url
                }
                response = requests.post(
                    "https://google.serper.dev/search",
                    headers=headers,
                    json={"q": prompt, "num": 20},
                    proxies=proxies
                )
            else:
                response = requests.post(
                    "https://google.serper.dev/search",
                    headers=headers,
                    json={"q": prompt, "num": 10}
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
            else:
                return "find no searching result"
        except requests.RequestException as e:
            self.logger.error(f"[System] RequestException: {e}")
            return f"RequestException: {str(e)}"
        except ValueError as e:
            self.logger.error(f"[System] JSON error: {e}")
            return f"JSON error: {str(e)}"
        except Exception as e:
            self.logger.error(f"[System] Unknown error: {e}")
            return f"unknown error: {str(e)}"

    async def process_response(self, response_text):
        """处理响应并触发语音播放"""
        try:
            # 提取有效响应内容（移除<think>标签等内容）
            ai_response = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()
            self.logger.info(f"original ai_response: {ai_response}")
                        
            # 清理Markdown格式符号（增强版）
            markdown_patterns = [
                (r'(#{1,6}\s*)|(\*{1,3}|_{1,3})', ''),  # 标题和强调符号
                (r'`{1,3}(.*?)`{1,3}', r'\1'),          # 代码块和内联代码
                (r'!?\[.*?\]\(.*?\)', ''),              # 图片和链接
                (r'-{3,}|={3,}', ''),                   # 分割线
                (r'>{1,}', ''),                         # 引用
                (r'\|\|.*?\|\|', ''),                   # 删除线
                (r'\s+', ' '),                          # 多个空格合并
                (r'^\s+|\s+$', '')                      # 首尾空格
                ]
            
            for pattern, replacement in markdown_patterns:
                ai_response = re.sub(pattern, replacement, ai_response, flags=re.MULTILINE)
            self.logger.info(f"ai_response: {ai_response}")
            if ai_response and self.is_voice_active:
                # 调用语音合成播放
#               await self.audio_util.say_response(ai_response)
                asyncio.creat_task(self.audio_util.say_response(ai_response))
            return ai_response
        except Exception as e:
            self.logger.error(f"响应处理失败: {str(e)}")
            return response_text
