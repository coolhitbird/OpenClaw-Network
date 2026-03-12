"""
OpenClaw Network - ClawMesh Message Format Definition

定义消息结构和编解码逻辑。

消息格式 (JSON):
{
  "meta": {
    "node_id": "CL-...",           # 发送方 node_id
    "timestamp": 1234567890,      # Unix timestamp (秒)
    "protocol_version": "1.0"
  },
  "payload": {
    "type": "text|image|audio|video|file",
    "content": "base64 string or utf-8 text",
    "encrypted": false,           # Phase 3 加密
    # 可选: "media_meta": {"size": 1234, "mime": "image/png", "name": "photo.jpg"}
  },
  "routing": {
    "to": "target_node_id | broadcast",
    "hops": ["CL-xxx", "CL-yyy"]  # 经过的节点（Phase 4 中继）
  }
}
"""

import json
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

@dataclass
class MessageMeta:
    node_id: str
    timestamp: int
    protocol_version: str = "1.0"

@dataclass
class MessagePayload:
    type: str  # "text", "image", "audio", "video", "file"
    content: str  # base64 or utf-8
    encrypted: bool = False
    media_meta: Optional[Dict[str, Any]] = None

@dataclass
class MessageRouting:
    to: str  # target node_id or "broadcast"
    hops: list = None  # list of node_ids

    def __post_init__(self):
        if self.hops is None:
            self.hops = []

@dataclass
class Message:
    """完整消息结构"""
    meta: MessageMeta
    payload: MessagePayload
    routing: MessageRouting

    def to_dict(self) -> dict:
        """序列化为字典（用于 JSON）"""
        return {
            "meta": asdict(self.meta),
            "payload": asdict(self.payload),
            "routing": asdict(self.routing)
        }

    def to_json(self) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> 'Message':
        """从字典反序列化"""
        meta = MessageMeta(**data.get("meta", {}))
        payload = MessagePayload(**data.get("payload", {}))
        routing = MessageRouting(**data.get("routing", {}))
        return cls(meta=meta, payload=payload, routing=routing)

    @classmethod
    def from_json(cls, json_str: str) -> 'Message':
        """从 JSON 字符串反序列化"""
        data = json.loads(json_str)
        return cls.from_dict(data)

    @classmethod
    def create_text(cls, from_node_id: str, to: str, text: str) -> 'Message':
        """工厂方法：创建文本消息"""
        return cls(
            meta=MessageMeta(
                node_id=from_node_id,
                timestamp=int(time.time()),
                protocol_version="1.0"
            ),
            payload=MessagePayload(
                type="text",
                content=text,
                encrypted=False
            ),
            routing=MessageRouting(to=to)
        )

def create_handshake(node_id: str, public_key: Optional[str] = None, signature: Optional[str] = None) -> dict:
    """创建 handshake 消息字典"""
    return {
        "type": "node.handshake",
        "node_id": node_id,
        "public_key": public_key,
        "signature": signature
    }

def create_handshake_ack(
    node_id: str,
    public_key: Optional[str] = None,
    fingerprint: Optional[str] = None,
    trusted: bool = True
) -> dict:
    """创建 handshake_ack 消息字典"""
    return {
        "type": "node.handshake_ack",
        "node_id": node_id,
        "public_key": public_key,
        "fingerprint": fingerprint,
        "trusted": trusted
    }

def create_ping(timestamp: Optional[int] = None) -> dict:
    """创建 ping 消息"""
    if timestamp is None:
        timestamp = int(time.time())
    return {
        "type": "node.ping",
        "timestamp": timestamp
    }

def create_pong(timestamp: int) -> dict:
    """创建 pong 响应"""
    return {
        "type": "node.pong",
        "timestamp": timestamp
    }

# 测试用示例
if __name__ == "__main__":
    # 创建消息示例
    msg = Message.create_text("CL-test123", "broadcast", "Hello ClawMesh!")
    print("Message JSON:")
    print(msg.to_json())

    # 解析
    parsed = Message.from_json(msg.to_json())
    print("\nParsed back:", parsed.meta.node_id, parsed.payload.content)

    # Handshake 示例
    hs = create_handshake("CL-node1")
    print("\nHandshake:", json.dumps(hs, indent=2))

    # Handshake ack
    ack = create_handshake_ack("CL-server", fingerprint="abc123", trusted=True)
    print("\nHandshake ack:", json.dumps(ack, indent=2))
