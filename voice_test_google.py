import speech_recognition as sr

r = sr.Recognizer()

# 使用麦克风测试
with sr.Microphone() as source:
    print("请说话...")
    r.adjust_for_ambient_noise(source, duration=1)
    audio = r.listen(source, timeout=5, phrase_time_limit=5)
    
try:
    text = r.recognize_google(audio, language="zh-CN")
    print(f"识别结果: {text}")
    print("✅ Google语音识别服务工作正常")
except sr.UnknownValueError:
    print("❌ 无法识别语音内容（可能麦克风问题或语音不清晰）")
except sr.RequestError as e:
    print(f"❌ API请求失败: {e}")
    print("可能的原因：网络代理问题、Google服务暂时不可用")
except Exception as e:
    print(f"❌ 其他错误: {e}")