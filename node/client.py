"""
OpenClaw Network - ClawMesh WebSocket Client (Phase 1)

异步 WebSocket 客户端，用于节点间通信和 handshake 发起。

Phase 1 特性:
- 主动连接服务器
- 发送 handshake
- 接收 handshake_ack
- 发送/接收消息
- 自动重连（Basic）

运行: uv run python node/client.py <server-url> [--node-id EXISTING_ID]
示例: uv run python node/client.py ws://localhost:8765
"""

import asyncio
import json
import logging
import sys
import argparse
from typing import Optional
import websockets

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class ClawMeshClient:
    """ClawMesh 节点客户端"""

    def __init__(self, node_id: str, server_url: str):
        self.node_id = node_id
        self.server_url = server_url
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.connected = asyncio.Event()
        self.shutdown = False
        self._reconnect_delay = 5  # seconds

    async def connect(self):
        """连接到服务器"""
        logger.info(f"Connecting to {self.server_url} as {self.node_id}")
        while not self.shutdown:
            try:
                self.websocket = await websockets.connect(
                    self.server_url,
                    ping_interval=20,
                    ping_timeout=30
                )
                self.connected.set()
                logger.info("Connected successfully")

                # 发送 handshake
                handshake = {
                    "type": "node.handshake",
                    "node_id": self.node_id,
                    "public_key": None,  # Phase 3
                    "signature": None   # Phase 3
                }
                await self.websocket.send(json.dumps(handshake))
                logger.info("Handshake sent")

                # 等待 handshake_ack
                raw = await self.websocket.recv()
                try:
                    ack = json.loads(raw)
                except json.JSONDecodeError:
                    logger.error("Invalid handshake_ack JSON")
                    await self.websocket.close()
                    continue

                if ack.get("type") != "node.handshake_ack":
                    logger.error(f"Expected handshake_ack, got: {ack.get('type')}")
                    await self.websocket.close()
                    continue

                # TODO: Phase 3 验证 fingerprint 和 signature
                logger.info(f"Handshake complete. Server: {ack.get('node_id')}, trusted: {ack.get('trusted')}")

                # 进入消息循环
                await self.message_loop()

            except (websockets.exceptions.ConnectionClosed, OSError) as e:
                logger.warning(f"Connection lost: {e}")
                self.connected.clear()
                if not self.shutdown:
                    logger.info(f"Reconnecting in {self._reconnect_delay}s...")
                    await asyncio.sleep(self._reconnect_delay)
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)
                if not self.shutdown:
                    await asyncio.sleep(self._reconnect_delay)

    async def message_loop(self):
        """接收服务器消息"""
        try:
            async for raw in self.websocket:
                try:
                    msg = json.loads(raw)
                    msg_type = msg.get("type")
                    logger.debug(f"Received: {msg_type}")

                    if msg_type == "message":
                        await self.handle_message(msg)
                    elif msg_type == "node.handshake_ack":
                        logger.info("Received extra handshake_ack (should be one-time)")
                    elif msg_type == "node.pong":
                        logger.debug("Pong received")
                    else:
                        logger.warning(f"Unknown message type: {msg_type}")
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON: {raw[:100]}")
        except websockets.exceptions.ConnectionClosed:
            logger.info("Connection closed by server")
            raise

    async def handle_message(self, msg: dict):
        """处理 incoming 消息"""
        sender = msg.get("meta", {}).get("node_id", "unknown")
        payload = msg.get("payload", {})
        content = payload.get("content", "")
        logger.info(f"[FROM {sender}]: {content}")

    async def send_message(self, to: str, content: str, msg_type: str = "text"):
        """发送消息到指定节点或广播"""
        msg = {
            "meta": {
                "node_id": self.node_id,
                "timestamp": int(asyncio.get_event_loop().time()),
                "protocol_version": "1.0"
            },
            "payload": {
                "type": msg_type,
                "content": content,
                "encrypted": False  # Phase 3
            },
            "routing": {
                "to": to,
                "hops": []  # Phase 4 中继
            }
        }
        data = json.dumps(msg)
        # ClientConnection 没有 .open，检查是否还有 close 方法（即未关闭）
        if self.websocket is not None and not getattr(self.websocket, 'closed', True):
            try:
                await self.websocket.send(data)
                logger.debug(f"Sent to {to}: {content[:50]}")
            except Exception as e:
                logger.error(f"Send failed: {e}")
                raise
        else:
            logger.error("Cannot send: not connected")
            raise ConnectionError("Not connected")

    async def broadcast(self, content: str):
        """广播消息"""
        await self.send_message("broadcast", content)

    async def close(self):
        """关闭连接"""
        self.shutdown = True
        if self.websocket:
            await self.websocket.close()
        logger.info("Client stopped")

async def main():
    parser = argparse.ArgumentParser(description="ClawMesh Node Client")
    parser.add_argument("server_url", help="WebSocket server URL, e.g. ws://localhost:8765")
    parser.add_argument("--node-id", default=None, help="Existing node_id (generates new if not provided)")
    args = parser.parse_args()

    # 生成或使用 node_id
    if args.node_id:
        node_id = args.node_id
    else:
        # 临时生成一个用于测试
        from adapter.node_id import generate_node_id
        node_id = generate_node_id('S')
        logger.info(f"Generated temporary node_id: {node_id}")

    client = ClawMeshClient(node_id=node_id, server_url=args.server_url)

    # 信号处理（跨平台）
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    try:
        # Unix: 使用 add_signal_handler
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
    except NotImplementedError:
        # Windows: 使用同步信号处理
        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}, shutting down...")
            stop_event.set()
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    logger.info("Press Ctrl+C to stop client")

    # 启动连接任务
    connect_task = asyncio.create_task(client.connect())

    # 等待停止信号
    await stop_event.wait()
    connect_task.cancel()
    await client.close()

if __name__ == "__main__":
    import signal
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Client interrupted")
