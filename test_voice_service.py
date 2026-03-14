import unittest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import speech_recognition as sr

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.voice_service import VoiceRecognitionService

class TestVoiceRecognitionService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = MagicMock()
        self.logger.info.side_effect = lambda msg: print(f"LOG: {msg}")
        self.logger.error.side_effect = lambda msg: print(f"ERROR: {msg}")
        self.logger.warning.side_effect = lambda msg: print(f"WARN: {msg}")
        
        self.ws_handler = MagicMock()
        self.ws_handler.connected_clients = []
        self.service = VoiceRecognitionService(self.logger, self.ws_handler)
        self.service.audio_util.say_response = AsyncMock()

    @patch('speech_recognition.Recognizer')
    @patch('speech_recognition.Microphone')
    @patch('asyncio.to_thread')
    @patch('random.choice')
    @patch('pygame.mixer.get_init')
    @patch('pygame.mixer.music.get_busy')
    async def test_wake_word_response(self, mock_get_busy, mock_get_init, mock_random_choice, mock_to_thread, mock_mic, mock_recognizer):
        # Set up mocks
        mock_get_init.return_value = True
        mock_get_busy.return_value = False
        mock_random_choice.return_value = "有什么我能帮你的吗？"
        
        self.service.recognizer = mock_recognizer.return_value
        self.service.recognizer.adjust_for_ambient_noise = MagicMock()

        async def mock_to_thread_impl(func, *args, **kwargs):
            if func == self.service.recognizer.listen:
                return MagicMock()
            elif func == self.service.recognizer.recognize_google:
                return "小弟 今天天气怎么样"
            return None
        
        mock_to_thread.side_effect = mock_to_thread_impl
        
        mock_mic.return_value.__enter__.return_value = MagicMock(spec=sr.AudioSource)
        
        original_say = self.service.audio_util.say_response
        async def mock_say(text, *args, **kwargs):
            print(f"DEBUG: say_response called with: {text}")
            self.service.is_listening = False
            return await original_say(text, *args, **kwargs)
        self.service.audio_util.say_response.side_effect = mock_say

        await self.service.start_listening()

        self.service.audio_util.say_response.assert_any_call("有什么我能帮你的吗？")
        self.assertTrue(self.service.has_started)
        self.assertEqual(self.service.full_query, "今天天气怎么样")

    @patch('speech_recognition.Recognizer')
    @patch('speech_recognition.Microphone')
    @patch('asyncio.to_thread')
    @patch('pygame.mixer.get_init')
    @patch('pygame.mixer.music.get_busy')
    async def test_submit_query_confirmation(self, mock_get_busy, mock_get_init, mock_to_thread, mock_mic, mock_recognizer):
        # Set up mocks
        mock_get_init.return_value = True
        mock_get_busy.return_value = False
        # Simulate a conversation already started
        self.service.has_started = True
        self.service.full_query = "北京的天气"
        
        self.service.recognizer = mock_recognizer.return_value
        self.service.recognizer.adjust_for_ambient_noise = MagicMock()

        async def mock_to_thread_impl(func, *args, **kwargs):
            if func == self.service.recognizer.listen:
                return MagicMock()
            elif func == self.service.recognizer.recognize_google:
                return "就这样"
            return None

        mock_to_thread.side_effect = mock_to_thread_impl
        
        mock_mic.return_value.__enter__.return_value = MagicMock(spec=sr.AudioSource)
        
        original_submit = self.service.submit_query
        async def mock_submit():
            res = await original_submit()
            self.service.is_listening = False
            return res
        self.service.submit_query = mock_submit

        await self.service.start_listening()

        expected_msg = "好的，您的问题是：北京的天气。请稍后。"
        self.service.audio_util.say_response.assert_any_call(expected_msg)
        
        self.assertEqual(self.service.audio_queue.qsize(), 1)
        query = await self.service.audio_queue.get()
        self.assertEqual(query, "北京的天气")

if __name__ == '__main__':
    unittest.main()
