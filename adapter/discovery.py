"""
ClawMesh - Node Discovery (Phase 2)

节点发现模块：从预设列表和 UDP 广播中自动发现网络节点。

模块结构：
- KnownNodesLoader: 加载并管理 config/known_nodes.json
- UDPBroadcaster: 发送/接收 UDP 广播发现请求
- NodeRegistry: 合并预设与发现节点，处理冲突
"""

import json
import time
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, asdict
import socket
import struct

logger = logging.getLogger(__name__)

# ============== Data Structures ==============

@dataclass
class NodeInfo:
    """节点信息"""
    node_id: str
    address: str  # WebSocket URL, e.g. ws://192.168.1.100:8765
    description: Optional[str] = None
    tags: List[str] = None
    source: str = "preset"  # "preset" or "udp"
    last_seen: float = None  # 时间戳
    metadata: Dict[str, any] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.metadata is None:
            self.metadata = {}
        if self.last_seen is None:
            self.last_seen = time.time()

    def to_dict(self) -> dict:
        """序列化为字典（用于 JSON）"""
        return asdict(self)

@dataclass
class DiscoveryConfig:
    """发现配置"""
    enabled: bool = True
    udp_port: int = 9876
    broadcast_interval: float = 30.0  # seconds
    conflict_resolution: str = "preset_priority"  # preset_priority|udp_priority|merge_latest
    known_nodes_file: str = "config/known_nodes.json"

# ============== Known Nodes Loader ==============

class KnownNodesLoader:
    """
    加载和管理已知节点列表（预设节点）

    支持热重载（文件修改检测）
    """

    def __init__(self, config: DiscoveryConfig):
        self.config = config
        self.presets: Dict[str, NodeInfo] = {}
        self._last_mtime: float = 0
        self._file_path: Optional[Path] = None

    async def load(self, project_root: Path) -> bool:
        """
        加载 known_nodes.json

        Args:
            project_root: 项目根目录（如 projects/ClawMesh）

        Returns:
            True 如果加载成功，False 如果文件不存在或格式错误
        """
        file_path = project_root / self.config.known_nodes_file
        if not file_path.exists():
            logger.warning(f"known_nodes.json not found: {file_path}")
            return False

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 解析 bootstrap 节点（高优先级）
            loaded = {}
            for item in data.get("bootstrap", []):
                node = self._parse_node_item(item, "bootstrap")
                loaded[node.node_id] = node

            # 解析 known_peers 节点
            for item in data.get("known_peers", []):
                node = self._parse_node_item(item, "peer")
                # peer 不覆盖 bootstrap
                if node.node_id not in loaded:
                    loaded[node.node_id] = node

            self.presets = loaded
            self._last_mtime = file_path.stat().st_mtime
            self._file_path = file_path

            logger.info(f"Loaded {len(self.presets)} known nodes from {file_path}")
            return True

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse known_nodes.json: {e}")
            return False
        except Exception as e:
            logger.error(f"Error loading known_nodes.json: {e}")
            return False

    def _parse_node_item(self, item: dict, category: str) -> NodeInfo:
        """解析单个节点配置项"""
        node_id = item.get("node_id")
        address = item.get("address")
        if not node_id or not address:
            raise ValueError(f"Invalid node item: missing node_id or address")

        return NodeInfo(
            node_id=node_id,
            address=address,
            description=item.get("description"),
            tags=item.get("tags", []) + [category],
            source="preset",
            last_seen=time.time(),
            metadata={"category": category, "raw": item}
        )

    async def check_reload(self, project_root: Path) -> bool:
        """
        检查文件是否修改，如有则重载

        Returns:
            True 如果文件被重载（内容变化），False 如果没有
        """
        if self._file_path is None:
            return await self.load(project_root)

        if not self._file_path.exists():
            return False

        current_mtime = self._file_path.stat().st_mtime
        if current_mtime > self._last_mtime:
            logger.info(f"known_nodes.json modified, reloading...")
            old_presets = self.presets.copy()
            success = await self.load(project_root)
            if success:
                # 返回是否有变化
                return self.presets != old_presets
            return False
        return False

    def get_preset(self, node_id: str) -> Optional[NodeInfo]:
        """获取预设节点信息"""
        return self.presets.get(node_id)

    def list_presets(self) -> List[NodeInfo]:
        """列出所有预设节点"""
        return list(self.presets.values())

    def has_preset(self, node_id: str) -> bool:
        """检查节点是否在预设列表中"""
        return node_id in self.presets

# ============== UDP Broadcaster ==============

class UDPBroadcaster:
    """
    UDP 广播发现协议

    协议：
      Request: {"type": "discovery.request", "node_id": "...", "timestamp": ...}
      Response: {"type": "discovery.response", "node_id": "...", "ws_address": "...", "timestamp": ...}
    """

    def __init__(self, config: DiscoveryConfig, own_node_id: str):
        self.config = config
        self.own_node_id = own_node_id
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._listening = False
        self._discovered: Dict[str, NodeInfo] = {}
        self._lock = asyncio.Lock()

    async def start(self):
        """启动 UDP 监听"""
        if self._listening:
            return

        loop = asyncio.get_event_loop()
        try:
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: UDPProtocol(self),
                local_addr=('0.0.0.0', self.config.udp_port),
                family=socket.AF_INET
            )
            self._listening = True
            logger.info(f"UDP broadcaster listening on port {self.config.udp_port}")
        except OSError as e:
            logger.error(f"Failed to start UDP broadcaster: {e} (port {self.config.udp_port} may be in use or blocked)")
            raise

    async def stop(self):
        """停止 UDP 监听"""
        if self._transport:
            self._transport.close()
            self._transport = None
            self._listening = False
            logger.info("UDP broadcaster stopped")

    async def broadcast_request(self, interval: float = None):
        """
        定期广播发现请求

        Args:
            interval: 广播间隔（秒），默认使用配置值
        """
        if interval is None:
            interval = self.config.broadcast_interval

        while self._listening:
            try:
                await self._send_request()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error broadcasting discovery request: {e}")
                await asyncio.sleep(interval)

    async def _send_request(self):
        """发送单次发现请求广播"""
        if not self._transport:
            return

        msg = {
            "type": "discovery.request",
            "node_id": self.own_node_id,
            "timestamp": int(time.time())
        }
        data = json.dumps(msg).encode('utf-8')

        # 广播到所有网络接口（255.255.255.255）
        try:
            self._transport.sendto(data, ('255.255.255.255', self.config.udp_port))
            logger.debug(f"Sent discovery request to 255.255.255.255:{self.config.udp_port}")
        except Exception as e:
            logger.error(f"Failed to send UDP broadcast: {e}")

    def handle_response(self, addr: tuple, data: bytes):
        """
        处理 UDP 响应（从其他节点）

        Args:
            addr: (ip, port) 发送方地址
            data: JSON 载荷
        """
        try:
            msg = json.loads(data.decode('utf-8'))
            if msg.get("type") != "discovery.response":
                return

            node_id = msg.get("node_id")
            ws_address = msg.get("ws_address")
            if not node_id or not ws_address:
                logger.warning(f"Invalid discovery.response: missing fields")
                return

            # 忽略自己的响应
            if node_id == self.own_node_id:
                return

            async def add_discovered():
                async with self._lock:
                    self._discovered[node_id] = NodeInfo(
                        node_id=node_id,
                        address=ws_address,
                        source="udp",
                        last_seen=time.time(),
                        metadata={"udp_addr": addr, "raw": msg}
                    )
                    logger.info(f"Discovered node via UDP: {node_id} @ {ws_address}")

            asyncio.create_task(add_discovered())

        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON in UDP response from {addr}")
        except Exception as e:
            logger.error(f"Error handling UDP response: {e}")

    def get_discovered(self) -> Dict[str, NodeInfo]:
        """获取当前所有发现的节点（副本）"""
        return self._discovered.copy()

    def clear_discovered(self):
        """清空发现缓存（用于测试）"""
        self._discovered.clear()


class UDPProtocol(asyncio.DatagramProtocol):
    """UDP 协议处理"""

    def __init__(self, broadcaster: UDPBroadcaster):
        self.broadcaster = broadcaster

    def datagram_received(self, data: bytes, addr: tuple):
        self.broadcaster.handle_response(addr, data)

    def error_received(self, exc: Exception):
        logger.error(f"UDP protocol error: {exc}")


# ============== Node Registry ==============

class NodeRegistry:
    """
    节点注册表：合并预设列表和 UDP 发现

    策略：预设优先，UDP 补充
    """

    def __init__(self, loader: KnownNodesLoader, discovery: UDPBroadcaster):
        self.loader = loader
        self.discovery = discovery
        self._conflict_log: List[Dict] = []

    def get_all_nodes(self) -> List[NodeInfo]:
        """
        获取全部已知节点

        优先级：预设 > 发现
        冲突处理：如果 node_id 同时存在于两者且地址不同，记录警告，返回预设
        """
        nodes = []
        preset_ids = set(self.loader.presets.keys())

        # 添加预设节点
        for node in self.loader.list_presets():
            nodes.append(node)

        # 添加发现节点（不覆盖预设）
        discovered = self.discovery.get_discovered()
        for node_id, node in discovered.items():
            if node_id in preset_ids:
                # 冲突检查
                preset_node = self.loader.presets[node_id]
                if preset_node.address != node.address:
                    conflict = {
                        "node_id": node_id,
                        "preset_address": preset_node.address,
                        "udp_address": node.address,
                        "timestamp": time.time()
                    }
                    self._conflict_log.append(conflict)
                    logger.warning(
                        f"Node {node_id} 地址冲突：预设={preset_node.address} UDP={node.address}，"
                        f"使用预设"
                    )
                # 跳过 UDP 副本
                continue
            nodes.append(node)

        return nodes

    def get_node(self, node_id: str) -> Optional[NodeInfo]:
        """
        获取节点信息（预设优先）

        Returns:
            NodeInfo 或 None（如果未知）
        """
        # 优先预设
        preset = self.loader.get_preset(node_id)
        if preset:
            return preset

        # 其次发现
        discovered = self.discovery.get_discovered()
        return discovered.get(node_id)

    def get_conflicts(self) -> List[Dict]:
        """获取冲突记录"""
        return self._conflict_log.copy()

    def clear_conflicts(self):
        """清空冲突记录"""
        self._conflict_log.clear()

# ============== Factory ==============

def create_discovery_components(
    project_root: Path,
    own_node_id: str,
    config: DiscoveryConfig = None
) -> tuple[KnownNodesLoader, UDPBroadcaster, NodeRegistry]:
    """
    工厂函数：创建发现模块的三个组件

    Args:
        project_root: 项目根目录
        own_node_id: 本节点 ID
        config: 发现配置（默认使用 DiscoveryConfig()）

    Returns:
        (loader, broadcaster, registry)
    """
    if config is None:
        config = DiscoveryConfig()

    loader = KnownNodesLoader(config)
    broadcaster = UDPBroadcaster(config, own_node_id)
    registry = NodeRegistry(loader, broadcaster)

    return loader, broadcaster, registry
