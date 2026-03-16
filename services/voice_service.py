import speech_recognition as sr
from asyncio import Queue
import asyncio
from .audio_util import AudioUtil
import os
import socket
import random
import pygame
import time
import re
import threading

class VoiceRecognitionService:
    def __init__(self, logger, ws_handler=None):
        self.logger = logger
        self.recognizer = sr.Recognizer()
        # 优化：启用动态能量阈值，减少手动校准需求
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.energy_threshold = 300 
        self.is_listening = True
        self.audio_queue = Queue()
        self.full_query = ""
        self.has_started = False
        self.unrecognized_count = 0
        self.last_activity_time = time.time()
        self.max_retries = 3
        self.wake_words = ["小弟", "小迪", "小D", "老弟", "小安"]
        self.end_phrases = ["就这样", "结束", "完毕", "谢谢", "好了", "退出", "结束对话", "请回答"]
        self.ws_handler = ws_handler
        self.audio_util = AudioUtil()
        # 预编译唤醒词正则，提高匹配效率
        self.wake_word_pattern = re.compile(f"({'|'.join(self.wake_words)})")
        self._whisper_model = None
        self._whisper_lock = threading.Lock()

    def start(self):
        self.is_listening = True
        self.reset_state()

    def stop(self):
        """停止语音服务并清理资源"""
        self.is_listening = False
        self.logger.info("[Voice] 正在停止语音服务...")
        # 清理队列
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.reset_state()

    def reset_state(self):
        """重置会话状态"""
        self.full_query = ""
        self.has_started = False
        self.unrecognized_count = 0
        self.last_activity_time = time.time()
        self.logger.info("[Voice] 会话状态已重置")

    def detect_end_phrase(self, text):
        """检测结束语"""
        for phrase in self.end_phrases:
            if phrase in text:
                return True
        return False

    async def submit_query(self):
        """提交查询并播报确认"""
        if self.full_query:
            # 移除可能误录入的结束语
            for phrase in self.end_phrases:
                self.full_query = self.full_query.replace(phrase, "").strip()
            
            if not self.full_query:
                self.reset_state()
                return None

            self.logger.info(f"[Voice] 提交查询: {self.full_query}")
            await self.audio_util.say_response(f"好的，您的问题是：{self.full_query}。请稍后。", logger=self.logger)
            await self.audio_queue.put(self.full_query)
            query = self.full_query
            self.reset_state()
            return query
        return None

    async def say_ai_response(self, text):
        """播报 AI 回复"""
        if text:
            await self.audio_util.say_response(text, logger=self.logger)

    def _is_ai_talking(self):
        """检查 AI 是否正在说话"""
        return pygame.mixer.get_init() and pygame.mixer.music.get_busy()

    async def _handle_wake_word(self, text):
        """正则匹配唤醒词并处理"""
        match = self.wake_word_pattern.search(text)
        if match:
            wake_word = match.group(1)
            content = text.split(wake_word, 1)[-1].strip()
            
            if not self.has_started:
                self.has_started = True
                self.full_query = content
                self.logger.info(f"[Voice] 唤醒: {wake_word}, 初始内容: {content}")
                responses = ["在", "有什么我能帮你的吗？", "我在呢", "请说"]
                await self.audio_util.say_response(random.choice(responses), logger=self.logger)
            else:
                if content:
                    self.full_query = (self.full_query + " " + content).strip()
            return True
        return False

    async def start_listening(self):
        """主监听循环"""
        retry_count = 0
        while self.is_listening:
            try:
                while self._is_ai_talking() and self.is_listening:
                    await asyncio.sleep(0.5)

                with sr.Microphone() as source:
                    if retry_count == 0:
                        self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                        self.logger.info("[Voice] 麦克风已就绪，等待唤醒...")

                    while self.is_listening:
                        if self._is_ai_talking(): break

                        try:
                            audio = await asyncio.to_thread(
                                self.recognizer.listen, source, timeout=1, phrase_time_limit=10
                            )
                            from config import config
                            speech_cfg = config.get("SPEECH_RECOGNITION_CONFIG", {}) if isinstance(config, dict) else {}
                            provider = str(speech_cfg.get("PROVIDER", "google")).strip().lower()

                            if provider == "whisper_local":
                                recognize_fn = self._recognize_whisper
                                text = await asyncio.to_thread(recognize_fn, audio)
                            elif provider == "baidu":
                                app_key = str(speech_cfg.get("BAIDU_APP_KEY", "")).strip()
                                secret_key = str(speech_cfg.get("BAIDU_SECRET_KEY", "")).strip()
                                if not app_key or not secret_key:
                                    raise sr.RequestError("Baidu credentials missing")
                                recognize_fn = self.recognizer.recognize_baidu
                                text = await asyncio.to_thread(
                                    recognize_fn, audio, app_key, secret_key, language="zh"
                                )
                            else:
                                recognize_fn = self.recognizer.recognize_google
                                text = await asyncio.to_thread(
                                    recognize_fn, audio, language="zh-CN"
                                )
                            
                            if not text: continue
                            self.last_activity_time = time.time()
                            self.unrecognized_count = 0

                            # 唤醒词处理
                            is_wake = await self._handle_wake_word(text)
                            if not is_wake and self.has_started:
                                self.full_query = (self.full_query + " " + text).strip()
                                self.logger.info(f"[Voice] 记录中: {self.full_query}")

                            # 提交逻辑
                            if self.has_started and self.full_query:
                                if self.detect_end_phrase(text):
                                    return await self.submit_query()

                        except sr.WaitTimeoutError:
                            if self.has_started and self.full_query:
                                if time.time() - self.last_activity_time >= 2.0:
                                    self.logger.info("[Voice] 静默超时提交")
                                    return await self.submit_query()
                        
                        except sr.UnknownValueError:
                            if self.has_started:
                                self.unrecognized_count += 1
                                if self.unrecognized_count >= 2:
                                    self.logger.info("[Voice] 连续无法识别提交")
                                    return await self.submit_query()
                        
                        except sr.RequestError as e:
                            self.logger.error(f"[Voice] 识别服务请求失败: {e}")
                            await asyncio.sleep(2)
                            break

            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger.error(f"[Voice] 运行异常: {e}")
                retry_count += 1
                await asyncio.sleep(min(retry_count, 5))
                if retry_count > self.max_retries:
                    self.logger.error("[Voice] 重试次数过多，停止服务")
                    self.stop()
                    break

        self.logger.info("[Voice] 语音服务已完全停止")

    def _recognize_whisper(self, audio: sr.AudioData) -> str:
        from config import config
        speech_cfg = config.get("SPEECH_RECOGNITION_CONFIG", {}) if isinstance(config, dict) else {}
        model_name = str(speech_cfg.get("WHISPER_MODEL", "small")).strip() or "small"
        device = str(speech_cfg.get("WHISPER_DEVICE", "cuda")).strip().lower() or "cuda"
        compute_type = str(speech_cfg.get("WHISPER_COMPUTE_TYPE", "")).strip().lower()
        download_root = str(speech_cfg.get("WHISPER_DOWNLOAD_ROOT", "")).strip()
        if download_root:
            os.makedirs(download_root, exist_ok=True)

        try:
            import numpy as np
        except Exception as e:
            raise sr.RequestError(f"numpy missing: {e}")

        raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

        with self._whisper_lock:
            if self._whisper_model is None:
                try:
                    from faster_whisper import WhisperModel
                except Exception as e:
                    raise sr.RequestError(f"faster-whisper missing: {e}")

                if not compute_type:
                    compute_type = "float16" if device == "cuda" else "int8"
                try:
                    kwargs = {"device": device, "compute_type": compute_type}
                    if download_root:
                        kwargs["download_root"] = download_root
                    self._whisper_model = WhisperModel(model_name, **kwargs)
                except Exception as e:
                    if device != "cpu":
                        try:
                            kwargs = {"device": "cpu", "compute_type": "int8"}
                            if download_root:
                                kwargs["download_root"] = download_root
                            self._whisper_model = WhisperModel(model_name, **kwargs)
                        except Exception as e2:
                            raise sr.RequestError(
                                f"whisper_local init failed: {e2}. If HuggingFace is unreachable, download the model in advance and set WHISPER_MODEL to a local folder, or set WHISPER_DOWNLOAD_ROOT to an existing cache directory."
                            )
                    else:
                        raise sr.RequestError(
                            f"whisper_local init failed: {e}. If HuggingFace is unreachable, download the model in advance and set WHISPER_MODEL to a local folder, or set WHISPER_DOWNLOAD_ROOT to an existing cache directory."
                        )

            segments, info = self._whisper_model.transcribe(samples, language="zh")
            text = "".join(seg.text for seg in segments).strip()
            if not text:
                raise sr.UnknownValueError()
            return text
