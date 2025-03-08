import pytest
import logging
from services.chat_handler import ChatHandler

class TestResponseProcessing:
    @pytest.fixture
    async def setUp(self):
        # Setup logger
        logger = logging.getLogger('test')
        logger.setLevel(logging.INFO)
        # Initialize ChatHandler
        self.handler = ChatHandler(logger)
        return self.handler
    @pytest.mark.asyncio
    async def test_markdown_cleanup(self, setUp):
        self.handler = await setUp
        test_cases = [
            ("# 标题", "标题"),
            ("##标题", "标题"),
            ("文本**加粗**内容", "文本内容"),
            ("`代码块`保留", "保留"),
            ("[链接](url)", ""),
            ("***混合***格式", "格式"),
            ("正常*符号使用", "正常符号使用"),
            ("5*3=15", "5*3=15")  # Fixed to preserve mathematical operators
        ]
        
        for input_text, expected in test_cases:
            result = await self.handler.process_response(input_text)
            assert result == expected, f"Failed for input: {input_text}"