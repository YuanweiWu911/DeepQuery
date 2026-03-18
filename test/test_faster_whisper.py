#!/usr/bin/env python3
"""
Faster-Whisper 功能演示脚本
演示 faster-whisper 的语音识别能力，包括实时麦克风识别和音频文件识别
"""

import os
import time
import numpy as np
import speech_recognition as sr
from faster_whisper import WhisperModel
import asyncio
import threading
from datetime import datetime

class FasterWhisperDemo:
    def __init__(self, model_size="small", device="cpu", compute_type="int8"):
        """
        初始化 faster-whisper 演示类
        
        Args:
            model_size: 模型大小 (tiny, base, small, medium, large-v2, large-v3)
            device: 运行设备 (cpu, cuda)
            compute_type: 计算类型 (int8, float16, float32)
        """
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model = None
        self.recognizer = sr.Recognizer()
        
        # 性能统计
        self.stats = {
            "total_audio_duration": 0,
            "total_processing_time": 0,
            "total_segments": 0
        }
    
    def load_model(self):
        """加载 faster-whisper 模型"""
        print(f"🚀 正在加载 faster-whisper 模型: {self.model_size}")
        print(f"   设备: {self.device}, 计算类型: {self.compute_type}")
        
        start_time = time.time()
        
        proxy_url = os.environ.get("HTTP_PROXY") or "http://127.0.0.1:7890"
        os.environ["HTTP_PROXY"] = proxy_url
        os.environ["HTTPS_PROXY"] = proxy_url
        os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
        print(f"🔗 使用代理: {proxy_url}")
        
        try:
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                download_root="./whisper_models"
            )
            load_time = time.time() - start_time
            print(f"✅ 模型加载成功! 耗时: {load_time:.2f}秒")
            return True
        except Exception as e:
            print(f"❌ 模型加载失败: {e}")
            
            # 检查是否是代理相关错误
            if "proxy" in str(e).lower() or "connection" in str(e).lower():
                print(f"💡 代理连接问题，尝试不使用代理...")
                try:
                    # 重试不使用代理
                    self.model = WhisperModel(
                        self.model_size,
                        device=self.device,
                        compute_type=self.compute_type,
                        download_root="./whisper_models"
                    )
                    load_time = time.time() - start_time
                    print(f"✅ 模型加载成功 (无代理)! 耗时: {load_time:.2f}秒")
                    return True
                except Exception as e2:
                    print(f"❌ 无代理加载也失败: {e2}")
            
            return False
    
    def transcribe_audio_file(self, audio_file_path):
        """
        转录音频文件
        
        Args:
            audio_file_path: 音频文件路径
        """
        if not os.path.exists(audio_file_path):
            print(f"❌ 音频文件不存在: {audio_file_path}")
            return
        
        print(f"🎵 开始转录音频文件: {audio_file_path}")
        
        try:
            start_time = time.time()
            
            # 使用 faster-whisper 进行转录
            segments, info = self.model.transcribe(
                audio_file_path,
                language="zh",  # 指定中文
                beam_size=5,
                best_of=5,
                temperature=0.0,
                vad_filter=True,  # 启用语音活动检测
                vad_parameters=dict(min_silence_duration_ms=500)
            )
            
            processing_time = time.time() - start_time
            
            print(f"\n📊 转录结果:")
            print(f"   语言检测: {info.language} (概率: {info.language_probability:.2%})")
            print(f"   处理时长: {processing_time:.2f}秒")
            print(f"   实时因子: {info.duration / processing_time:.2f}x")
            
            full_text = ""
            print("\n📝 识别内容:")
            for segment in segments:
                print(f"   [{segment.start:.2f}s -> {segment.end:.2f}s]: {segment.text}")
                full_text += segment.text
                self.stats["total_segments"] += 1
            
            self.stats["total_audio_duration"] += info.duration
            self.stats["total_processing_time"] += processing_time
            
            print(f"\n📄 完整文本: {full_text}")
            
        except Exception as e:
            print(f"❌ 转录失败: {e}")
    
    def real_time_microphone_recognition(self, duration_seconds=10):
        """
        实时麦克风语音识别
        
        Args:
            duration_seconds: 识别时长（秒）
        """
        print(f"🎤 开始实时语音识别 ({duration_seconds}秒)...")
        print("   请对着麦克风说话...")
        
        try:
            with sr.Microphone() as source:
                # 调整环境噪音
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
                print("✅ 麦克风准备就绪")
                
                start_time = time.time()
                segments_collected = []
                
                while time.time() - start_time < duration_seconds:
                    try:
                        # 监听语音（1秒超时）
                        audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=5)
                        
                        # 转换为 faster-whisper 需要的格式
                        raw_data = audio.get_raw_data(convert_rate=16000, convert_width=2)
                        samples = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
                        
                        # 实时转录
                        segments, info = self.model.transcribe(
                            samples,
                            language="zh",
                            beam_size=3,
                            vad_filter=True
                        )
                        
                        for segment in segments:
                            if segment.text.strip():
                                current_time = time.time() - start_time
                                print(f"[{current_time:5.1f}s] {segment.text}")
                                segments_collected.append(segment)
                                self.stats["total_segments"] += 1
                        
                    except sr.WaitTimeoutError:
                        # 超时是正常的，继续监听
                        continue
                    except Exception as e:
                        print(f"识别错误: {e}")
                        continue
                
                print("\n📋 实时识别汇总:")
                full_text = "".join(seg.text for seg in segments_collected)
                print(f"完整内容: {full_text}")
                
        except Exception as e:
            print(f"❌ 实时识别失败: {e}")
    
    def benchmark_performance(self, test_audio_file=None):
        """性能基准测试"""
        print("\n🧪 开始性能基准测试...")
        
        if test_audio_file and os.path.exists(test_audio_file):
            # 测试文件转录性能
            self.transcribe_audio_file(test_audio_file)
        
        # 测试不同模型大小的性能
        model_sizes = ["tiny", "base", "small"]
        
        for size in model_sizes:
            print(f"\n🔬 测试模型: {size}")
            
            try:
                test_model = WhisperModel(size, device="cpu", compute_type="int8", download_root="./whisper_models")
                
                # 创建测试音频（1秒静音 + 测试语音）
                test_audio = np.zeros(16000 * 2, dtype=np.float32)  # 2秒音频
                
                start_time = time.time()
                segments, info = test_model.transcribe(test_audio, language="zh")
                processing_time = time.time() - start_time
                
                print(f"   加载时间: {processing_time:.2f}秒")
                print(f"   内存占用: 约 {self._estimate_model_size(size)} MB")
                
            except Exception as e:
                print(f"   测试失败: {e}")
    
    def _estimate_model_size(self, model_size):
        """估算模型大小"""
        sizes = {
            "tiny": 75,
            "base": 140,
            "small": 460,
            "medium": 1400,
            "large-v2": 2900,
            "large-v3": 2900
        }
        return sizes.get(model_size, 0)
    
    def print_stats(self):
        """打印统计信息"""
        print("\n📈 性能统计:")
        print(f"   总音频时长: {self.stats['total_audio_duration']:.2f}秒")
        print(f"   总处理时间: {self.stats['total_processing_time']:.2f}秒")
        print(f"   总识别段数: {self.stats['total_segments']}")
        
        if self.stats['total_audio_duration'] > 0:
            real_time_factor = self.stats['total_audio_duration'] / self.stats['total_processing_time']
            print(f"   平均实时因子: {real_time_factor:.2f}x")

def main():
    """主函数"""
    print("=" * 60)
    print("🎯 Faster-Whisper 功能演示")
    print("=" * 60)
    
    # 创建演示实例
    demo = FasterWhisperDemo(
        model_size="small",  # 可以改为 tiny, base, small, medium, large-v3
        device="cpu",        # 如果有GPU可以改为 cuda
        compute_type="int8"   # 可以改为 float16 (GPU) 或 float32
    )
    
    # 1. 加载模型
    if not demo.load_model():
        return
    
    # 2. 实时麦克风识别演示
    print("\n" + "=" * 40)
    print("🎤 实时麦克风识别演示")
    print("=" * 40)
    demo.real_time_microphone_recognition(duration_seconds=15)
    
    # 3. 音频文件识别演示（如果有测试文件）
    test_files = [
        "./test_audio.wav",
        "./audio_sample.wav",
        "./test.wav"
    ]
    
    for test_file in test_files:
        if os.path.exists(test_file):
            print("\n" + "=" * 40)
            print(f"🎵 音频文件识别演示: {test_file}")
            print("=" * 40)
            demo.transcribe_audio_file(test_file)
    
    # 4. 性能基准测试
    print("\n" + "=" * 40)
    print("🧪 性能基准测试")
    print("=" * 40)
    demo.benchmark_performance()
    
    # 5. 打印统计信息
    demo.print_stats()
    
    print("\n" + "=" * 60)
    print("✅ 演示完成!")
    print("=" * 60)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⏹️  演示被用户中断")
    except Exception as e:
        print(f"\n\n❌ 演示出错: {e}")
    finally:
        print("\n感谢使用 Faster-Whisper 演示!")
