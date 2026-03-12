"""
OpenClaw Network - ClawMesh WebSocket Server (Phase 1)

异步 WebSocket 服务器，处理节点连接、handshake 和消息路由。

Phase 1 特性:
- 明文 handshake (Phase 3 加密)
- 1对1 消息转发
- 广播支持
- 连接池管理

运行: uv run python node/server.py [--host HOST] [--port PORT]
"""

import asyncio
import json
import logging
import signal
import sys
from dataclasses import dataclass, field
from typing import Dict, Set, Optional
import argparse
import websockets

# 配置日志（UTF-8 safe）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

@dataclass
class Peer:
    """连接的节点信息"""
    websocket: websockets.WebSocketServerProtocol
    node_id: str
    remote_addr: tuple
    # 可扩展：公钥、验证状态等

class ClawMeshServer:
    """ClawMesh WebSocket 服务器"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765, max_connections: int = 100):
        self.host = host
        self.port = port
        self.max_connections = max_connections
        self.connections: Dict[str, Peer] = {}  # node_id -> Peer
        self.websocket_to_peer: Dict[websockets.WebSocketServerProtocol, Peer] = {}
        self.shutdown_flag = False
        self._server: Optional[websockets.WebSocketServer] = None

    async def start(self):
        """启动服务器"""
        logger.info(f"Starting ClawMesh server on {self.host}:{self.port}")
        self._server = await websockets.serve(
            self.handle_connection,
            self.host,
            self.port,
            ping_interval=20,
            ping_timeout=30
        )
        logger.info("Server started, waiting for connections...")

        # 等待关闭信号
        try:
            await self.wait_for_shutdown()
        finally:
            await self.stop()

    async def handle_connection(self, websocket: websockets.WebSocketServerProtocol, path: str = "/"):
        """处理新连接"""
        remote_addr = websocket.remote_address
        logger.info(f"New connection from {remote_addr}")

        # 检查连接数限制
        if len(self.connections) >= self.max_connections:
            logger.warning(f"Max connections ({self.max_connections}) reached, rejecting {remote_addr}")
            await websocket.close(code=1008, reason="Too many connections")
            return

        peer: Optional[Peer] = None
        try:
            # 第一步：接收 handshake 消息
            raw = await websocket.recv()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON from {remote_addr}: {raw[:200]}")
                await websocket.close(code=1003, reason="Invalid JSON")
                return

            # 验证 handshake 格式
            if msg.get("type") != "node.handshake":
                logger.error(f"Expected handshake, got: {msg.get('type')}")
                await websocket.close(code=1003, reason="Expected handshake")
                return

            node_id = msg.get("node_id")
            public_key = msg.get("public_key")  # Phase 3 使用
            signature = msg.get("signature")    # Phase 3 使用

            if not node_id:
                logger.error(f"Handshake missing node_id from {remote_addr}")
                await websocket.close(code=1003, reason="Missing node_id")
                return

            # 检查 node_id 是否已存在
            if node_id in self.connections:
                logger.warning(f"Node {node_id} already connected, replacing old connection")
                old_peer = self.connections[node_id]
                await old_peer.websocket.close(code=1001, reason="Replaced by new connection")
                self._remove_peer(old_peer)

            # 创建 Peer 记录
            peer = Peer(websocket=websocket, node_id=node_id, remote_addr=remote_addr)
            self.connections[node_id] = peer
            self.websocket_to_peer[websocket] = peer

            logger.info(f"Node {node_id} connected (total: {len(self.connections)})")

            # 发送 handshake_ack
            ack = {
                "type": "node.handshake_ack",
                "node_id": self._get_own_node_id(),  # 需要配置或生成
                "public_key": None,  # Phase 3 生成
                "fingerprint": "00000000",  # Phase 3 计算
                "trusted": True  # Phase 1 简化
            }
            await websocket.send(json.dumps(ack))

            # 广播新节点加入（可选，Phase 4 频道功能）
            # await self.broadcast({"type": "node.announce_join", "node_id": node_id}, exclude=node_id)

            # 主消息循环
            await self.handle_peer_messages(peer)

        except websockets.exceptions.ConnectionClosed as e:
            logger.info(f"Connection closed from {remote_addr}: {e}")
        except Exception as e:
            logger.error(f"Error handling connection {remote_addr}: {e}", exc_info=True)
        finally:
            if peer:
                self._remove_peer(peer)
                logger.info(f"Node {peer.node_id} disconnected (total: {len(self.connections)})")

    async def handle_peer_messages(self, peer: Peer):
        """接收并路由来自单个节点的消息"""
        async for raw in peer.websocket:
            try:
                msg = json.loads(raw)
                msg_type = msg.get("type")
                logger.debug(f"Received from {peer.node_id}: {msg_type}")

                # 消息路由
                if msg_type == "message":
                    await self.handle_message(peer, msg)
                elif msg_type == "node.ping":
                    await self.handle_ping(peer, msg)
                else:
                    logger.warning(f"Unknown message type from {peer.node_id}: {msg_type}")

            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from {peer.node_id}: {raw[:200]}")
            except Exception as e:
                logger.error(f"Error processing message from {peer.node_id}: {e}", exc_info=True)

    async def handle_message(self, sender: Peer, msg: dict):
        """处理消息类型"""
        # 必填字段
        to = msg.get("to")
        if not to:
            logger.warning(f"Message missing 'to' field from {sender.node_id}")
            return

        payload = msg.get("payload", {})
        content = payload.get("content", "")

        logger.info(f"Message from {sender.node_id} to {to}: {content[:50]}...")

        if to == "broadcast":
            # 广播给所有其他节点
            await self.broadcast(msg, exclude=sender.node_id)
        else:
            # 单播给特定节点
            target_peer = self.connections.get(to)
            if target_peer:
                try:
                    await target_peer.websocket.send(json.dumps(msg))
                    logger.debug(f"Forwarded message to {to}")
                except Exception as e:
                    logger.error(f"Failed to send to {to}: {e}")
            else:
                logger.warning(f"Target node {to} not found, message dropped")

    async def handle_ping(self, sender: Peer, msg: dict):
        """处理心跳"""
        pong = {"type": "node.pong", "timestamp": msg.get("timestamp")}
        try:
            await sender.websocket.send(json.dumps(pong))
        except Exception as e:
            logger.error(f"Failed to send pong to {sender.node_id}: {e}")

    async def broadcast(self, msg: dict, exclude: Optional[str] = None):
        """广播消息给所有连接（可排除某个节点）"""
        data = json.dumps(msg)
        tasks = []
        for node_id, peer in self.connections.items():
            if exclude and node_id == exclude:
                continue
            tasks.append(self._safe_send(peer, data))
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            # 统计失败
            failures = sum(1 for r in results if isinstance(r, Exception))
            if failures:
                logger.warning(f"Broadcast had {failures}/{len(tasks)} failures")

    async def _safe_send(self, peer: Peer, data: str):
        """安全发送，捕获异常"""
        try:
            await peer.websocket.send(data)
        except Exception as e:
            logger.debug(f"Send to {peer.node_id} failed: {e}")
            raise

    def _remove_peer(self, peer: Peer):
        """从连接池移除节点"""
        self.connections.pop(peer.node_id, None)
        self.websocket_to_peer.pop(peer.websocket, None)

    def _get_own_node_id(self) -> str:
        """返回服务器自身 node_id（需预先配置）"""
        # TODO: 从配置文件读取或动态生成
        return "CL-0000000000000000000000"  # 占位符

    async def wait_for_shutdown(self):
        """等待关闭信号（跨平台实现）"""
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        # Windows 不支持 add_signal_handler，使用不同策略
        try:
            # Unix/Linux/Mac: 使用信号处理
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, stop_event.set)
            logger.info("Press Ctrl+C to stop server")
            await stop_event.wait()
        except NotImplementedError:
            # Windows: 使用同步 signal.signal  + 轮询
            import threading

            def signal_handler(sig, frame):
                logger.info(f"Received signal {sig}, shutting down...")
                stop_event.set()

            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            logger.info("Press Ctrl+C to stop server")
            while not stop_event.is_set():
                await asyncio.sleep(0.1)

        logger.info("Shutdown signal received")

    async def stop(self):
        """优雅关闭"""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Server stopped")

def main():
    """CLI 入口"""
    parser = argparse.ArgumentParser(description="ClawMesh WebSocket Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind")
    args = parser.parse_args()

    server = ClawMeshServer(host=args.host, port=args.port)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Server interrupted")

if __name__ == "__main__":
    main()
