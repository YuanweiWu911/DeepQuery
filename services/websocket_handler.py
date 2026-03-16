import websockets
import asyncio
import logging
from asyncio import Queue

class WebSocketHandler:
    """Manages WebSocket connections and log distribution.
    
    Implements pub-sub pattern for real-time log streaming to connected clients.
    
    Attributes:
        log_queue (Queue): Buffer for log messages
        connected_clients (set): Active WebSocket connections
    """

    def __init__(self, logger):
        """Initializes WebSocket handler with empty client set and log queue."""
        self.log_queue = Queue()
        self.connected_clients = set()
        self._send_locks = {}
        self.logger = logger

    async def handle_ws(self, websocket, path=None):
        """Main WebSocket connection handler.
        
        Args:
            websocket (websockets.WebSocketServerProtocol): Client connection object
            path (Optional[str]): Request path (unused)
            
        Flow:
            1. Adds client to connected set
            2. Continuously sends queued logs
            3. Handles graceful disconnect
        """
        self.connected_clients.add(websocket)
        self._send_locks[websocket] = asyncio.Lock()
        try:
            async for message in websocket:
                if message == "QueryComplete":
                    self.logger.info("[WebSocket] 收到前端 QueryComplete 信号")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.connected_clients.discard(websocket)
            self._send_locks.pop(websocket, None)

    async def safe_send(self, websocket, message: str):
        lock = self._send_locks.get(websocket)
        if lock is None:
            return
        async with lock:
            await websocket.send(message)

    async def log_consumer(self):
        # 处理日志消费的逻辑
        while True:
            log_entry = await self.log_queue.get()
            for client in list(self.connected_clients):
                try:
                    await self.safe_send(client, log_entry)
                except websockets.exceptions.ConnectionClosed:
                    self.connected_clients.discard(client)
                    self._send_locks.pop(client, None)

    async def start_ws_server(self):
        server = await websockets.serve(self.handle_ws, "localhost", 8765)
        await server.wait_closed()
