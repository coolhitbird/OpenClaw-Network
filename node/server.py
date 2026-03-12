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
import base64
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Set, Optional
import argparse
import websockets

from adapter.crypto import CryptoManager
from adapter.node_id import generate_node_id
from cryptography.hazmat.primitives import serialization

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
    # Phase 3: 加密状态
    crypto: Optional['CryptoManager'] = None
    encryption_mode: str = "optional"  # required|optional|disabled

class ClawMeshServer:
    """ClawMesh WebSocket 服务器"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765, max_connections: int = 100, node_id: Optional[str] = None):
        self.host = host
        self.port = port
        self.max_connections = max_connections
        self.node_id = node_id or self._load_or_generate_node_id()
        self.connections: Dict[str, Peer] = {}  # node_id -> Peer
        self.websocket_to_peer: Dict[websockets.WebSocketServerProtocol, Peer] = {}
        self.shutdown_flag = False
        self._server: Optional[websockets.WebSocketServer] = None
        self._config_encryption_required = True  # Phase 3: require encryption by default
        self._config_encryption_required = True  # Phase 3: 默认要求加密

    def _load_or_generate_node_id(self) -> str:
        """加载或生成 node_id"""
        from adapter.node_id import generate_node_id
        config_path = Path("config") / "node_id.txt"
        try:
            if config_path.exists():
                return config_path.read_text(encoding='utf-8').strip()
            else:
                node_id = generate_node_id()
                config_path.parent.mkdir(parents=True, exist_ok=True)
                config_path.write_text(node_id, encoding='utf-8')
                return node_id
        except Exception as e:
            logger.warning(f"Failed to load/generate node_id: {e}, generating new")
            return generate_node_id()
    
    def server_supports_encryption(self) -> bool:
        """服务器是否支持加密"""
        return True  # Phase 3 默认支持
    
    def _get_own_node_id(self) -> str:
        """获取服务器 node_id"""
        return self.node_id

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
            # 第一步：接收 handshake 消息（明文或已加密？始终明文 handshake）
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
            client_pubkey_b64 = msg.get("public_key")
            client_encryption_mode = msg.get("encryption_mode", "optional")

            if not node_id:
                logger.error(f"Handshake missing node_id from {remote_addr}")
                await websocket.close(code=1003, reason="Missing node_id")
                return

            # Phase 3: 处理 ECDH 密钥交换
            encryption_mode = "optional"  # server 偏好（可配置）
            client_crypto: Optional[CryptoManager] = None
            
            if client_pubkey_b64 and self.server_supports_encryption():
                try:
                    client_pubkey_bytes = base64.b64decode(client_pubkey_b64)
                    logger.info(f"Client pubkey: len={len(client_pubkey_bytes)} bytes, first bytes: {client_pubkey_bytes[:4].hex()}")
                    
                    # 创建 server 端 CryptoManager
                    server_crypto = CryptoManager(self._get_own_node_id())
                    server_crypto.generate_keypair()
                    
                    # 计算共享密钥
                    shared = server_crypto.compute_shared_secret(client_pubkey_bytes)
                    server_crypto.derive_encryption_key(shared)
                    
                    # 协商加密模式
                    if client_encryption_mode == "required" and not self.server_supports_encryption():
                        # 客户端要求加密但服务器不支持
                        await websocket.send(json.dumps({
                            "type": "node.handshake_ack",
                            "node_id": self._get_own_node_id(),
                            "encryption_mode": "unsupported",
                            "reason": "Server does not support encryption"
                        }))
                        await websocket.close(code=1003, reason="Encryption required but not supported")
                        return
                    
                    encryption_mode = "required" if self.server_supports_encryption() else "optional"
                    
                    # 指纹验证（可选）
                    server_fingerprint = server_crypto.fingerprint
                    logger.info(f"Server fingerprint: {server_fingerprint}")
                    # TODO: 保存 client public key 用于后续验证
                    
                except Exception as e:
                    logger.error(f"ECDH handshake failed: {e}", exc_info=True)
                    await websocket.close(code=1003, reason="Invalid encryption key")
                    return
            else:
                # 明文 handshake 或客户端不支持加密
                if self.config.encryption_required and client_encryption_mode != "fallback":
                    await websocket.send(json.dumps({
                        "type": "node.handshake_ack",
                        "node_id": self._get_own_node_id(),
                        "encryption_mode": "unsupported",
                        "reason": "Server requires encryption"
                    }))
                    await websocket.close(code=1003, reason="Encryption required")
                    return
                encryption_mode = "disabled"
                server_crypto = None

            # 检查 node_id 是否已存在
            if node_id in self.connections:
                logger.warning(f"Node {node_id} already connected, replacing old connection")
                old_peer = self.connections[node_id]
                await old_peer.websocket.close(code=1001, reason="Replaced by new connection")
                self._remove_peer(old_peer)

            # 创建 Peer 记录
            peer = Peer(
                websocket=websocket,
                node_id=node_id,
                remote_addr=remote_addr,
                crypto=server_crypto,
                encryption_mode=encryption_mode
            )
            self.connections[node_id] = peer
            self.websocket_to_peer[websocket] = peer

            logger.info(f"Node {node_id} connected (encryption={encryption_mode}, total: {len(self.connections)})")

            # 发送 handshake_ack
            # Phase 3: 如果支持加密，附带 server 公钥和指纹
            try:
                if server_crypto:
                    server_pubkey = server_crypto.key_pair.public_key()
                    logger.info(f"Server pubkey for ack: has_key_pair={server_crypto.key_pair is not None}")
                    server_pub_bytes = server_pubkey.public_bytes(
                        encoding=serialization.Encoding.X962,
                        format=serialization.PublicFormat.UncompressedPoint
                    )
                    logger.info(f"Server pub_bytes for ack: len={len(server_pub_bytes)}, first4={server_pub_bytes[:4].hex()}")
                    public_key_b64 = base64.b64encode(server_pub_bytes).decode('ascii')
                    fingerprint = server_crypto.fingerprint
                else:
                    public_key_b64 = None
                    fingerprint = None
            except Exception as e:
                logger.error(f"Error preparing ack: {e}", exc_info=True)
                raise
            
            ack = {
                "type": "node.handshake_ack",
                "node_id": self._get_own_node_id(),
                "public_key": public_key_b64,
                "fingerprint": fingerprint,
                "trusted": True,
                "encryption_mode": encryption_mode
            }
            await websocket.send(json.dumps(ack))
            logger.debug(f"Sent handshake_ack to {node_id} (encryption_mode={encryption_mode})")

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
                
                # Phase 3: 解密 inbound 消息（如果加密）
                payload = msg.get("payload", {})
                if payload.get("encrypted", False):
                    if not peer.crypto:
                        logger.warning(f"Received encrypted message from {peer.node_id} but no crypto available")
                        await peer.websocket.close(code=1003, reason="Encrypted message but no session key")
                        return
                    try:
                        # 解密 payload（需要将 payload 对象转为 JSON 字符串再解密）
                        import json as _json
                        payload_json = _json.dumps(payload, ensure_ascii=False)
                        decrypted_json = peer.crypto.decrypt_message({"content": payload["content"]})
                        # 替换 payload 为解密后的对象
                        msg["payload"] = _json.loads(decrypted_json)
                        logger.debug(f"Decrypted message from {peer.node_id}")
                    except Exception as e:
                        logger.error(f"Failed to decrypt message from {peer.node_id}: {e}")
                        await peer.websocket.close(code=1003, reason="Decryption failed")
                        return
                
                # 提取消息类型：从 payload.type 获取
                payload = msg.get("payload", {})
                msg_type = payload.get("type")
                logger.debug(f"Received from {peer.node_id}: {msg_type}")

                # 消息路由
                if msg_type == "text":
                    await self.handle_message(peer, msg)
                elif msg_type == "node.ping":
                    await self.handle_ping(peer, msg)
                elif msg_type is None:
                    logger.warning(f"Message missing payload.type from {peer.node_id}")
                else:
                    logger.warning(f"Unknown message type from {peer.node_id}: {msg_type}")

            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from {peer.node_id}: {raw[:200]}")
            except Exception as e:
                logger.error(f"Error processing message from {peer.node_id}: {e}", exc_info=True)

    async def handle_message(self, sender: Peer, msg: dict):
        """处理消息类型"""
        # 必填字段：从 routing 中获取目标
        to = msg.get("routing", {}).get("to")
        if not to:
            logger.warning(f"Message missing 'routing.to' field from {sender.node_id}")
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
