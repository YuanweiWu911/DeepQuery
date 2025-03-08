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
        try:
            async for message in websocket:
                if message == "QueryComplete":
                    self.logger.info("[WebSocket] 收到前端 QueryComplete 信号")
                elif not self.log_queue.empty():
                    log_entry = await self.log_queue.get()
                    await websocket.send(log_entry)
        except websockets.exceptions.ConnectionClosedOK:
            pass
        finally:
            self.connected_clients.remove(websocket)

    async def log_consumer(self):
        # 处理日志消费的逻辑
        while True:
            if not self.log_queue.empty():
                log_entry = await self.log_queue.get()
#               if not self.connected_clients:
#                   self.logger.warning("[WebSocket] 无活跃客户端")
                for client in self.connected_clients:
                    try:
                        await client.send(log_entry)
                    except websockets.exceptions.ConnectionClosedOK:
                        self.connected_clients.remove(client)
            await asyncio.sleep(0.01)

    async def start_ws_server(self):
        server = await websockets.serve(self.handle_ws, "localhost", 8765)
        await server.wait_closed()

