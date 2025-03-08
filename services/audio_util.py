import edge_tts
import pygame
from io import BytesIO
import asyncio

class AudioUtil:
    @staticmethod
    async def say_response(text, voice="zh-CN-XiaoyiNeural", logger=None):
        """使用 edge_tts 生成音频并通过 pygame 播放
        
        Args:
            text (str): 要播放的文本
            voice (str): 使用的语音模型，默认为 "zh-CN-YunyangNeural"
            logger (logging.Logger, optional): 日志记录器，用于记录播放状态
            
            "zh-CN-YunxiNeural"    # 青年男声（默认）
            "zh-CN-YunyangNeural"   # 新闻男声
            "zh-CN-XiaoxiaoNeural"  # 年轻女声（多情感）
            "zh-CN-XiaoyiNeural"    # 少女音
            "zh-CN-YunjianNeural"   # 成熟男声

        """
        try:
            if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
            communicate = edge_tts.Communicate(text, voice)
            audio_stream = BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_stream.write(chunk["data"])
            audio_stream.seek(0)

            pygame.mixer.init()
            pygame.mixer.music.load(audio_stream)
            pygame.mixer.music.play()
            
            # 等待播放完成
            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.1)
                
            if logger:
                logger.info(f"[Voice] 播放语音: {text[:50]}...")
            
        except Exception as e:
            if logger:
                logger.error(f"[Voice] 语音播放失败: {str(e)}")

