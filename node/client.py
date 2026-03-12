"""
OpenClaw Network - ClawMesh WebSocket Client (Phase 1 + Phase 3 Crypto)

异步 WebSocket 客户端，用于节点间通信和 handshake 发起。

Phase 1 特性:
- 主动连接服务器
- 发送 handshake
- 接收 handshake_ack
- 发送/接收消息
- 自动重连（Basic）

Phase 3 特性:
- ECDH 密钥交换
- AES-GCM 消息加密
- 指纹验证

运行: uv run python node/client.py <server-url> [--node-id EXISTING_ID]
示例: uv run python node/client.py ws://localhost:12448
"""

import asyncio
import json
import logging
import sys
import argparse
import base64
from pathlib import Path
from typing import Optional
import websockets
import websockets

from adapter.crypto import CryptoManager, get_trusted_fingerprints

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
        # Phase 3: 加密状态
        self.crypto: Optional[CryptoManager] = None
        self.encryption_mode: str = "optional"
        self.trusted_fingerprints = get_trusted_fingerprints()

    async def connect(self):
        """连接到服务器（支持加密 handshake）"""
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

                # Phase 3: 生成临时 ECDH 密钥对
                client_crypto = CryptoManager(self.node_id)
                client_pubkey_bytes = client_crypto.generate_keypair()
                client_pubkey_b64 = base64.b64encode(client_pubkey_bytes).decode('ascii')
                
                # 发送 handshake（包含公钥，要求加密）
                handshake = {
                    "type": "node.handshake",
                    "node_id": self.node_id,
                    "public_key": client_pubkey_b64,
                    "encryption_mode": "required"
                }
                await self.websocket.send(json.dumps(handshake))
                logger.info(f"Handshake sent (fingerprint: {client_crypto.fingerprint})")

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

                server_encryption_mode = ack.get("encryption_mode", "optional")
                server_pubkey_b64 = ack.get("public_key")
                server_fingerprint = ack.get("fingerprint")
                
                # 检查加密模式
                if handshake["encryption_mode"] == "required" and server_encryption_mode != "required":
                    logger.error(f"Server requires encryption but mode={server_encryption_mode}")
                    await self.websocket.close()
                    continue
                
                self.encryption_mode = server_encryption_mode
                
                # 计算共享密钥
                if server_pubkey_b64 and server_encryption_mode != "disabled":
                    try:
                        server_pubkey_bytes = base64.b64decode(server_pubkey_b64)
                        client_crypto.compute_shared_secret(server_pubkey_bytes)
                        client_crypto.derive_encryption_key(client_crypto.compute_shared_secret(server_pubkey_bytes))
                        self.crypto = client_crypto
                        logger.info(f"Encryption handshake complete, server fingerprint: {server_fingerprint}")
                        
                        # 指纹验证
                        if server_fingerprint:
                            expected = self.trusted_fingerprints.get(ack.get("node_id"))
                            if expected:
                                if expected != server_fingerprint:
                                    logger.warning(f"Fingerprint mismatch! stored={expected}, got={server_fingerprint}")
                            else:
                                # 首次连接，存储指纹（生产环境应询问用户）
                                logger.warning(f"First connection to {ack.get('node_id')}, accepting fingerprint: {server_fingerprint}")
                                self.trusted_fingerprints.set(ack.get("node_id"), server_fingerprint)
                    except Exception as e:
                        logger.error(f"ECDH failed: {e}")
                        await self.websocket.close()
                        continue
                else:
                    logger.warning("Encryption disabled (server does not support)")
                    self.crypto = None

                # Handshake 完成，进入消息接收循环
                await self._receive_loop()

            except (websockets.exceptions.ConnectionClosed, OSError) as e:
                self.connected.clear()
                if not self.shutdown:
                    logger.warning(f"Connection lost, retrying in {self._reconnect_delay}s...")
                    await asyncio.sleep(self._reconnect_delay)
            except Exception as e:
                logger.error(f"Unexpected error in connect loop: {e}", exc_info=True)
                if not self.shutdown:
                    await asyncio.sleep(self._reconnect_delay)

    async def _receive_loop(self):
        """接收服务器消息（支持解密）"""
        try:
            async for raw in self.websocket:
                try:
                    msg = json.loads(raw)
                    
                    # Phase 3: 解密 payload（如果加密）
                    payload = msg.get("payload", {})
                    if payload.get("encrypted", False):
                        if not self.crypto:
                            logger.warning("Received encrypted message but no crypto")
                            await self.websocket.close(code=1003, reason="No encryption session")
                            return
                        try:
                            import json as _json
                            decrypted = self.crypto.decrypt_message({"content": payload["content"]})
                            msg["payload"] = _json.loads(decrypted)
                            logger.debug("Decrypted inbound message")
                        except Exception as e:
                            logger.error(f"Decryption failed: {e}")
                            await self.websocket.close(code=1003, reason="Decryption error")
                            return
                    
                    msg_type = msg.get("type")
                    logger.debug(f"Received: {msg_type}")

                    if msg_type == "message":
                        await self.handle_message(msg)
                    elif msg_type == "node.handshake_ack":
                        logger.info("Received extra handshake_ack (ignored)")
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
        """发送消息到指定节点或广播（支持加密）"""
        payload = {
            "type": msg_type,
            "content": content,
            "encrypted": False
        }
        
        # Phase 3: 如果加密会话建立，加密 payload
        if self.crypto and self.encryption_mode != "disabled":
            try:
                import json as _json
                payload_json = _json.dumps(payload, ensure_ascii=False)
                encrypted = self.crypto.encrypt_message(payload_json)
                payload = encrypted
            except Exception as e:
                logger.error(f"Failed to encrypt message: {e}")
                return False
        
        msg = {
            "meta": {
                "node_id": self.node_id,
                "timestamp": int(asyncio.get_event_loop().time()),
                "protocol_version": "1.0"
            },
            "payload": payload,
            "routing": {
                "to": to,
                "hops": []
            }
        }
        data = json.dumps(msg)
        # Check connection state: websockets uses state attribute (1=OPEN)
        if self.websocket is not None and getattr(self.websocket, 'state', 3) == 1:
            try:
                await self.websocket.send(data)
                logger.debug(f"Sent to {to}: {content[:50]}")
                return True
            except websockets.exceptions.ConnectionClosed as e:
                logger.error(f"Send failed: connection closed - {e}")
                return False
        else:
            logger.warning("Cannot send: not connected")
            return False

    async def broadcast(self, content: str):
        """广播消息"""
        await self.send_message("broadcast", content)

    async def close(self):
        """关闭连接"""
        self.shutdown = True
        if self.websocket:
            try:
                await self.websocket.close()
            except:
                pass
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
