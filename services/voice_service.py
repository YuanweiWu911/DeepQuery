import speech_recognition as sr
from asyncio import Queue
import asyncio
from .audio_util import AudioUtil
import socket

class VoiceRecognitionService:
    def __init__(self, logger, ws_handler=None):
        self.logger = logger
        self.recognizer = sr.Recognizer()
        self.is_listening = True
        self.audio_queue = Queue()
        self.last_query = ""
        self.full_query = ""
        self.has_started = False
        self.unrecognized_count = 0
        self.max_retries = 3  # 最大重试次数
        self.wake_words = ["小弟", "小迪", "小D"]
        self.ws_handler = ws_handler
        self.audio_util = AudioUtil()
    
    def stop(self):
        self.is_listening = False
        self.logger.info("[Voice] 语音服务已停止")
        # 增加清理音频队列逻辑
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.reset_state()

    def reset_state(self):
        self.full_query = ""
        self.has_started = False
        self.unrecognized_count = 0
        self.logger.info("[Voice] 会话状态已重置，准备新一轮对话")        
        
    def remove_leading_wake_words(self, text, wake_word):
        """
        从文本的开头去除重复的唤醒词。
        
        :param text: 原始文本
        :param wake_word: 唤醒词
        :return: 去除开头重复唤醒词后的文本
        """
        while text.startswith(wake_word):
            text = text[len(wake_word):].lstrip()
        return text

    async def start_listening(self):
        """核心语音监听循环，包含唤醒词检测和语音识别逻辑"""
        while self.is_listening:
            mic = None
            retry_count = 0
            try:
                # 初始化麦克风
                mic = sr.Microphone()
                with mic as source:
                    # 环境噪声校准
                    self.recognizer.adjust_for_ambient_noise(source, duration=2)
                    self.logger.info("[Voice] 麦克风校准完成，开始监听...")
                    
                    # 重置重试计数器
                    retry_count = 0
                    
                    # 主监听循环
                    while self.is_listening:
                        try:
                            # 实时语音捕获（异步执行同步方法）
                            audio = await asyncio.to_thread(
                                self.recognizer.listen,
                                source,
                                timeout=1,
                                phrase_time_limit=8  # 延长单次录音时间到5秒
                            )
                            
                            if not self.is_listening:
                                break

                            # 语音识别（异步执行同步方法）
                            self.logger.debug("[Voice] 开始语音识别...")
                            text = await asyncio.to_thread(
                                self.recognizer.recognize_google,
                                audio,
                                language="zh-CN",
                                show_all=False  # 只返回最佳结果
                            )

                            if not self.is_listening:
                                break
                            
                            # 唤醒词检测逻辑
                            wake_word_detected = None
                            for wake_word in self.wake_words:
                                if wake_word in text:
                                    wake_word_detected = wake_word
                                    break

                            # 如果检测到唤醒词
                            if wake_word_detected:
                                if not self.has_started:
                                    self.has_started = True
                                    # 使用remove_leading_wake_words去除所有开头的唤醒词
                                    self.full_query = self.remove_leading_wake_words(text, wake_word_detected)
                                    self.logger.info(f"[Voice] 检测到唤醒词'{wake_word_detected}'，开始记录查询: {self.full_query}")
                                    await self.audio_util.say_response("我在")
                                else:
                                    # 如果已经处于对话状态，去除所有唤醒词
                                    self.full_query = self.remove_leading_wake_words(text, wake_word_detected)
                                    self.logger.info(f"[Voice] 追加查询内容: {self.full_query}")
                            else:
                                # 如果没有检测到唤醒词，直接追加文本
                                self.full_query = (self.full_query + " " + text).strip()
                                self.logger.info(f"[Voice] 追加查询内容: {self.full_query}")
                            self.unrecognized_count = 0
                            continue

                        except sr.UnknownValueError:
                                self.logger.warning(f"[Voice] 无法识别语音输入 (环境噪音: {self.recognizer.energy_threshold})")
                                self.recognizer.adjust_for_ambient_noise(source, duration=1)
                                self.unrecognized_count += 1

                                # 如果连续2次无法识别且已有累积查询
                                if self.has_started and self.unrecognized_count >= 2 and self.full_query:
                                    self.logger.info(f"[Voice] 连续2次未识别，提交查询: {self.full_query}")
                                    await self.audio_queue.put(self.full_query)
                                    self.reset_state()
                                    continue

                                if not self.is_listening:
                                    break 

                        except sr.WaitTimeoutError:
                            if self.has_started and self.full_query and self.unrecognized_count >= 2:
                                await self.audio_queue.put(self.full_query)
                                self.reset_state()
                                continue
                            if not self.is_listening:
                                break
                            
                        except sr.RequestError as e:
                            self.logger.error(f"[Voice] 识别服务错误: {str(e)}")
                            # 指数退避重试
                            delay = min(2 ** retry_count, 30)  # 最大30秒
                            await asyncio.sleep(delay)
                            retry_count += 1
                            # 检查网络连接
                            # 添加网络连接检查方法
                            try:
                                socket.create_connection(("8.8.8.8", 53), timeout=3)
                                return True
                            except OSError:
                                await self.audio_util.say_response("网络连接失败")
                                self.stop()
                                return False
                            if not self.is_listening:
                                break
                            continue

            except OSError as e:
                    self.logger.error(f"[Voice] 麦克风不可用: {str(e)}")
                    retry_count += 1
                    self.logger.info(f"[Voice] 尝试重启麦克风 ({retry_count}/{self.max_retries})")
                    if mic:
                        mic.__exit__(None, None, None)
                        mic = None
                    await asyncio.sleep(2)  # 等待后重试
                    
                    if retry_count >= self.max_retries:
                        self.logger.error("[Voice] 麦克风重试次数耗尽，停止语音服务")
                        self.stop()
                        break
                    if not self.is_listening:
                        break
                    
            except Exception as e:
                    self.logger.error(f"[Voice] 未预期的错误: {str(e)}")
                    await asyncio.sleep(1)
                    break
                
            finally:
                    if mic:
                        mic.__exit__(None, None, None)
                        mic = None
            
            if not self.is_listening:
                self.logger.info("[Voice] 退出语音服务")
                break
