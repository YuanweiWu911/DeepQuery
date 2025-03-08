import logging
import asyncio

class WebSocketLogHandler(logging.Handler):
    def __init__(self, log_queue):
        # 先调用父类的构造函数，传递默认的日志级别
        super().__init__(level=logging.NOTSET)
        self.log_queue = log_queue

    def emit(self, record):
        # 处理日志发送的逻辑
        log_entry = self.format(record)
        try:
            self.log_queue.put_nowait(log_entry)
#           asyncio.run_coroutine_threadsafe(self.log_queue.put(log_entry), asyncio.get_event_loop())
        except asyncio.QueueFull:
            pass  # 队列满了，忽略这条日志

class StdoutLogger:
    def __init__(self, logger):
        # 初始化时传入日志记录器实例
        self.logger = logger

    def write(self, message):
        if message.strip():
            self.logger.info(message.strip())

    def flush(self):
        pass

    def isatty(self):
        return False
