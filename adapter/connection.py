"""
ClawMesh - Connection Pool (Phase 2)

连接池管理：管理 outgoing 连接（主动连接他人），包括自动重连、心跳、LRU 驱逐。

模块结构：
- OutgoingConnection: 单个连接生命周期管理
- ConnectionPool: 池化管理、广播、维护任务
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from collections import OrderedDict
import websockets
from websockets.exceptions import ConnectionClosed

from .message import Message, create_ping, create_pong

logger = logging.getLogger(__name__)

# ============== Data Structures ==============

@dataclass
class ConnectionConfig:
    """连接池配置"""
    pool_size: int = 50                    # 最大连接数
    retry_initial_interval: float = 5.0   # 首次重试等待（秒）
    retry_backoff: str = "exponential"    # exponential|linear
    retry_max_initial: int = 5            # 前 5 次快速重试
    retry_hourly: bool = True             # 5 次后每小时重试
    retry_max_hourly: int = 24            # 最大小时级重试次数（最多 24h）
    heartbeat_interval: float = 30.0      # 心跳间隔（秒）
    heartbeat_timeout: float = 10.0       # 心跳超时（秒）
    heartbeat_max_missed: int = 3         # 连续缺失判定 offline
    connect_timeout: float = 5.0          # 连接超时（秒）
    bandwidth_limit_kbps: int = 100       # 出站带宽限制（KB/s）
    bandwidth_burst_kbps: int = 200       # 突发带宽（KB/s）

@dataclass
class ConnectionState:
    """连接状态跟踪"""
    ONLINE = "online"
    OFFLINE = "offline"
    CONNECTING = "connecting"
    FAILED = "failed"

@dataclass
class OutgoingConnection:
    """
    单个 outgoing 连接管理

    属性：
      node_id: 目标节点 ID
      address: WebSocket 地址（ws://host:port）
      websocket: WebSocket 连接对象（如果连接成功）
      state: 连接状态（online/offline/connecting/failed）
      retry_count: 当前重试次数
      last_attempt: 上次重试时间戳
      last_seen: 上次收到消息时间（心跳检测）
      last_used: 最后使用时间（LRU 驱逐用）
    """
    node_id: str
    address: str
    config: ConnectionConfig

    websocket: Optional[websockets.WebSocketClientProtocol] = None
    state: str = ConnectionState.OFFLINE
    retry_count: int = 0
    last_attempt: float = 0.0
    last_seen: float = 0.0
    last_used: float = field(default_factory=time.time)
    
    # 后台任务
    _connect_task: Optional[asyncio.Task] = None
    _heartbeat_task: Optional[asyncio.Task] = None
    _shutdown: asyncio.Event = field(default_factory=asyncio.Event)

    # 统计
    total_attempts: int = 0
    successful_connections: int = 0
    last_error: Optional[str] = None

    def __str__(self):
        return f"OutgoingConnection({self.node_id} @ {self.address}, state={self.state}, retry={self.retry_count})"

    # ============ Public API ============

    async def start(self):
        """启动连接管理后台任务"""
        if self._connect_task is None:
            self._connect_task = asyncio.create_task(self._connect_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            logger.debug(f"Connection {self.node_id} background tasks started")

    async def stop(self):
        """停止连接，关闭所有任务"""
        self._shutdown.set()
        if self._connect_task:
            self._connect_task.cancel()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        await self.close()
        logger.debug(f"Connection {self.node_id} stopped")

    async def connect(self) -> bool:
        """
        建立 WebSocket 连接（一次性尝试）

        Returns:
            True 如果连接成功，False 如果失败
        """
        if self.state == ConnectionState.ONLINE:
            return True

        self.state = ConnectionState.CONNECTING
        self.total_attempts += 1

        try:
            # 带超时的连接
            self.websocket = await asyncio.wait_for(
                websockets.connect(self.address),
                timeout=self.config.connect_timeout
            )
            self.state = ConnectionState.ONLINE
            self.retry_count = 0  # 重置重试计数
            self.last_seen = time.time()
            self.successful_connections += 1
            logger.info(f"Connected to {self.node_id} @ {self.address}")
            return True

        except Exception as e:
            self.state = ConnectionState.FAILED
            self.last_error = str(e)
            logger.warning(f"Connection to {self.node_id} failed: {e}")
            return False

    async def send(self, msg: Message or dict) -> bool:
        """
        发送消息

        Args:
            msg: Message 对象或字典

        Returns:
            True 发送成功，False 失败
        """
        if self.state != ConnectionState.ONLINE or not self.websocket:
            logger.debug(f"Cannot send to {self.node_id}: not online")
            return False

        try:
            if isinstance(msg, Message):
                data = msg.to_json()
            else:
                import json
                data = json.dumps(msg, ensure_ascii=False)

            await self.websocket.send(data)
            self.last_used = time.time()  # 更新 LRU 时间戳
            return True
        except (ConnectionClosed, Exception) as e:
            logger.warning(f"Send to {self.node_id} failed: {e}")
            self.state = ConnectionState.OFFLINE
            self.websocket = None
            return False

    async def close(self):
        """关闭 WebSocket 连接"""
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception as e:
                logger.debug(f"Error closing websocket to {self.node_id}: {e}")
            finally:
                self.websocket = None
                if self.state == ConnectionState.ONLINE:
                    self.state = ConnectionState.OFFLINE
                logger.info(f"Connection to {self.node_id} closed")

    # ============ Internal Loops ============

    async def _connect_loop(self):
        """后台重连循环"""
        while not self._shutdown.is_set():
            try:
                if self.state in (ConnectionState.OFFLINE, ConnectionState.FAILED):
                    await self._attempt_reconnect()
                else:
                    # 状态良好，等待一段时间再检查
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in connect loop for {self.node_id}: {e}")
                await asyncio.sleep(1.0)

    async def _attempt_reconnect(self):
        """尝试重连（根据策略）"""
        if not self._should_retry():
            # 不应重试，等待更长时间
            await asyncio.sleep(60.0)  # 1 分钟检查一次
            return

        # 计算退避时间
        backoff = self._compute_backoff()
        now = time.time()
        if now - self.last_attempt < backoff:
            # 还没到重试时间
            await asyncio.sleep(backoff - (now - self.last_attempt))
            return

        self.last_attempt = time.time()
        logger.info(f"Reconnecting to {self.node_id} (attempt {self.retry_count + 1})...")
        
        success = await self.connect()
        if not success:
            self.retry_count += 1
            logger.warning(f"Reconnect to {self.node_id} failed, retry_count={self.retry_count}")
            # 失败后等待下一个退避周期
            await asyncio.sleep(backoff)
        else:
            logger.info(f"Reconnected to {self.node_id} successfully")

    def _should_retry(self) -> bool:
        """
        判断是否应该重试

        策略：
        - 前 5 次快速重试（总是重试）
        - 5 次后改为每小时重试（最多 24 次小时级重试）
        """
        if self.retry_count < self.config.retry_max_initial:
            return True
        
        if self.config.retry_hourly:
            # 每小时级重试，检查上次尝试时间
            now = time.time()
            hours_since_last = (now - self.last_attempt) / 3600.0
            if hours_since_last >= 1.0 and self.retry_count < (self.config.retry_max_hourly + self.config.retry_max_initial):
                return True
        
        return False

    def _compute_backoff(self) -> float:
        """计算重试退避时间"""
        if self.retry_count < self.config.retry_max_initial:
            # 指数退避: 5, 10, 20, 40, 60 秒
            return min(60.0, self.config.retry_initial_interval * (2 ** self.retry_count))
        else:
            # 5 次后每小时一次（3600 秒）
            return 3600.0

    async def _heartbeat_loop(self):
        """心跳检测循环"""
        while not self._shutdown.is_set():
            try:
                await asyncio.sleep(self.config.heartbeat_interval)
                if self.state != ConnectionState.ONLINE or not self.websocket:
                    continue

                # 发送 ping
                try:
                    ping_msg = create_ping(int(time.time()))
                    await self.send(ping_msg)
                    # 等待 pong 由 receive_loop 处理，这里只发送
                except Exception as e:
                    logger.warning(f"Heartbeat ping to {self.node_id} failed: {e}")
                    self.state = ConnectionState.OFFLINE
                    self.websocket = None

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat loop for {self.node_id}: {e}")

    # ============ Getters ============

    def is_online(self) -> bool:
        """是否在线（包括心跳检测）"""
        if self.state != ConnectionState.ONLINE:
            return False
        
        # 检查最后收到消息时间
        now = time.time()
        if self.config.heartbeat_max_missed > 0:
            max_idle = self.config.heartbeat_interval * self.config.heartbeat_max_missed + self.config.heartbeat_timeout
            if now - self.last_seen > max_idle:
                logger.info(f"Node {self.node_id} idle too long, marking offline")
                return False
        
        return True

    def get_stats(self) -> dict:
        """获取连接统计"""
        return {
            "node_id": self.node_id,
            "address": self.address,
            "state": self.state,
            "retry_count": self.retry_count,
            "total_attempts": self.total_attempts,
            "successful_connections": self.successful_connections,
            "last_seen": self.last_seen,
            "last_used": self.last_used,
            "last_error": self.last_error
        }

# ============== Connection Pool ==============

class ConnectionPool:
    """
    连接池管理

    功能：
    - 获取/创建 connection（get_connection）
    - 自动 LRU 驱逐
    - 广播消息
    - 后台维护（心跳、重连、清理）
    """

    def __init__(self, config: ConnectionConfig = None):
        self.config = config or ConnectionConfig()
        self._connections: Dict[str, OutgoingConnection] = {}
        self._lock = asyncio.Lock()
        self._maintenance_task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._closed = False

    async def start(self):
        """启动连接池后台维护任务"""
        if self._maintenance_task is None:
            self._maintenance_task = asyncio.create_task(self._maintain_loop())
            logger.info("ConnectionPool started")

    async def stop(self):
        """停止连接池，关闭所有连接"""
        self._shutdown.set()
        if self._maintenance_task:
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass
        
        # 关闭所有连接
        async with self._lock:
            for conn in self._connections.values():
                await conn.stop()
            self._connections.clear()
        
        self._closed = True
        logger.info("ConnectionPool stopped")

    async def get_connection(self, node_id: str, address: str) -> OutgoingConnection:
        """
        获取或创建连接

        Args:
            node_id: 目标节点 ID
            address: WebSocket 地址（如 ws://host:port）

        Returns:
            OutgoingConnection 对象
        """
        if self._closed:
            raise RuntimeError("ConnectionPool is closed")

        async with self._lock:
            # 已存在
            if node_id in self._connections:
                conn = self._connections[node_id]
                # 检查地址是否匹配（配置文件可能更新）
                if conn.address != address:
                    logger.warning(f"Node {node_id} address changed: {conn.address} -> {address}")
                    conn.address = address
                return conn

            # 检查连接池容量
            if len(self._connections) >= self.config.pool_size:
                await self._evict_lru()
            
            # 创建新连接
            conn = OutgoingConnection(
                node_id=node_id,
                address=address,
                config=self.config
            )
            self._connections[node_id] = conn
            await conn.start()
            logger.debug(f"Created connection to {node_id} @ {address}")
            return conn

    async def remove_connection(self, node_id: str):
        """显式移除连接（用于清理）"""
        async with self._lock:
            if node_id in self._connections:
                conn = self._connections.pop(node_id)
                await conn.stop()
                logger.debug(f"Removed connection to {node_id}")

    async def broadcast(self, msg: Message or dict, exclude: Optional[Set[str]] = None):
        """
        广播消息到所有在线连接

        Args:
            msg: 要发送的消息
            exclude: 排除的 node_id 集合
        """
        exclude = exclude or set()
        sent_count = 0
        async with self._lock:
            for node_id, conn in self._connections.items():
                if node_id in exclude:
                    continue
                if conn.is_online():
                    success = await conn.send(msg)
                    if success:
                        sent_count += 1
        
        logger.debug(f"Broadcast sent to {sent_count}/{len(self._connections)} nodes")
        return sent_count

    def get_connection_stats(self) -> Dict[str, any]:
        """获取连接池统计信息"""
        stats = {
            "total_connections": len(self._connections),
            "online": sum(1 for c in self._connections.values() if c.is_online()),
            "offline": sum(1 for c in self._connections.values() if not c.is_online()),
            "connections": [c.get_stats() for c in self._connections.values()]
        }
        return stats

    # ============ Maintenance ============

    async def _maintain_loop(self):
        """后台维护循环"""
        logger.info("ConnectionPool maintenance loop started")
        while not self._shutdown.is_set():
            try:
                await asyncio.sleep(10.0)  # 每 10 秒运行一次维护
                await self._maintain()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in maintenance loop: {e}")

    async def _maintain(self):
        """执行维护任务"""
        now = time.time()
        to_remove = []

        async with self._lock:
            for node_id, conn in self._connections.items():
                # 1. 检查连接健康
                if conn.state == ConnectionState.ONLINE:
                    # 检查最后收到消息时间
                    max_idle = self.config.heartbeat_interval * self.config.heartbeat_max_missed + self.config.heartbeat_timeout
                    if now - conn.last_seen > max_idle:
                        logger.warning(f"Connection {node_id} idle too long ({now-conn.last_seen:.0f}s), marking offline")
                        await conn.close()
                        to_remove.append(node_id)
                
                # 2. 统计日志（每 60 秒）
                # TODO: 可选的详细日志

        # 移除失效连接
        for node_id in to_remove:
            await self.remove_connection(node_id)
        
        # 记录统计
        stats = self.get_connection_stats()
        total_attempts = sum(c.total_attempts for c in self._connections.values())
        if total_attempts > 0:
            logger.debug(f"Pool stats: {stats['online']}/{stats['total_connections']} online, {total_attempts} total attempts")

    async def _evict_lru(self):
        """驱逐最久未使用的连接（LRU）"""
        if not self._connections:
            return
        
        # 找到 last_used 最小的连接
        oldest = min(self._connections.items(), key=lambda kv: kv[1].last_used)
        node_id, conn = oldest
        
        logger.warning(f"Pool full, evicting LRU connection: {node_id} (last used {time.time() - conn.last_used:.0f}s ago)")
        await conn.stop()
        del self._connections[node_id]

    # ============ Context Manager ============

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

# ============== Factory ==============

def create_connection_pool(config: ConnectionConfig = None) -> ConnectionPool:
    """
    创建连接池

    Args:
        config: 连接池配置（默认使用 ConnectionConfig()）

    Returns:
        ConnectionPool 实例
    """
    if config is None:
        config = ConnectionConfig()
    
    pool = ConnectionPool(config)
    return pool
