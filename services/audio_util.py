import edge_tts
import pygame
from io import BytesIO
import asyncio

class AudioUtil:
    @staticmethod
    async def say_response(text, voice="zh-CN-XiaoyiNeural", logger=None):
        """使用 edge_tts 生成音频并通过 pygame 播放"""
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
                
                communicate = edge_tts.Communicate(text, voice)
                audio_stream = BytesIO()
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio" and "data" in chunk:
                        audio_stream.write(chunk["data"])
                
                if audio_stream.tell() == 0:
                    raise ValueError("生成的音频数据为空")

                audio_stream.seek(0)
                pygame.mixer.init()
                pygame.mixer.music.load(audio_stream)
                pygame.mixer.music.play()
                
                while pygame.mixer.music.get_busy():
                    await asyncio.sleep(0.1)
                
                if logger:
                    logger.info(f"[Voice] 播放语音成功: {text[:50]}...")
                break # 成功则退出重试循环

            except asyncio.CancelledError:
                if logger:
                    logger.info("[Voice] 语音播放任务被取消")
                raise
            except Exception as e:
                if attempt < max_retries:
                    if logger:
                        logger.warning(f"[Voice] 语音播放尝试 {attempt + 1} 失败，正在重试... 错误: {str(e)}")
                    await asyncio.sleep(1) # 等待一秒后重试
                    continue
                if logger:
                    logger.error(f"[Voice] 语音播放最终失败: {str(e)}")

