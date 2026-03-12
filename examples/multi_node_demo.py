"""
ClawMesh Phase 2 - Multi-Node Demo

演示 3 个节点的完整网络：
1. Node A 作为 server（监听 12448）
2. Node B 和 Node C 作为 client，通过 discovery 自动发现 A
3. 使用 connection pool 管理 outgoing 连接
4. 测试：B→C 直接消息、C→B 广播、节点离线重连

运行: uv run python examples/multi_node_demo.py

注意: 此演示在同一进程中模拟多个节点，便于观察完整流程。
"""

import asyncio
import sys
import logging
from pathlib import Path
import time

# 配置日志（集中输出）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from adapter.node_id import generate_node_id
from node.server import ClawMeshServer
from node.client import ClawMeshClient
from adapter.discovery import KnownNodesLoader, UDPBroadcaster, NodeRegistry, DiscoveryConfig
from adapter.connection import ConnectionPool, ConnectionConfig, create_connection_pool

class DemoNode:
    """演示用的节点封装（包含 discovery + connection）"""
    
    def __init__(self, node_id: str, is_server: bool = False, server_url: str = None):
        self.node_id = node_id
        self.is_server = is_server
        self.server_url = server_url
        
        # 组件
        self.server: Optional[ClawMeshServer] = None
        self.client: Optional[ClawMeshClient] = None
        self.discovery_loader: Optional[KnownNodesLoader] = None
        self.discovery_broadcaster: Optional[UDPBroadcaster] = None
        self.discovery_registry: Optional[NodeRegistry] = None
        self.connection_pool: Optional[ConnectionPool] = None
        
        # 任务
        self._tasks: List[asyncio.Task] = []
        self._shutdown = asyncio.Event()

    async def start_server(self, host: str = "127.0.0.1", port: int = 12448):
        """启动 server 模式"""
        logger.info(f"[{self.node_id}] Starting server on {host}:{port}")
        self.server = ClawMeshServer(host=host, port=port)
        self.server_task = asyncio.create_task(self.server.start())
        await asyncio.sleep(1)  # 等待 server 绑定
        logger.info(f"[{self.node_id}] Server started")

    async def start_client(self, project_root: Path, enable_udp: bool = False):
        """启动 client 模式，包含 discovery 和 connection pool
        
        Args:
            enable_udp: 是否启用 UDP 广播发现（demo 中为 False 避免端口冲突）
        """
        logger.info(f"[{self.node_id}] Starting client, connecting to {self.server_url}")
        
        # 1. 初始化 discovery（不使用 UDP 广播，仅预设列表）
        disc_config = DiscoveryConfig(
            known_nodes_file="config/known_nodes.json",
            enabled=enable_udp  # 控制是否启动 UDP
        )
        self.discovery_loader = KnownNodesLoader(disc_config)
        await self.discovery_loader.load(project_root)
        
        if enable_udp:
            self.discovery_broadcaster = UDPBroadcaster(disc_config, self.node_id)
            try:
                await self.discovery_broadcaster.start()
            except OSError as e:
                logger.warning(f"[{self.node_id}] UDP start failed (port {disc_config.udp_port}): {e}, continuing without UDP")
            
            self.discovery_registry = NodeRegistry(
                self.discovery_loader,
                self.discovery_broadcaster,
                disc_config
            )
            # 启动 UDP 广播
            broadcast_task = asyncio.create_task(self.discovery_broadcaster.broadcast_request())
            self._tasks.append(broadcast_task)
        else:
            # 无 UDP，仅使用预设列表
            self.discovery_registry = NodeRegistry(
                self.discovery_loader,
                None,  # 无 broadcaster
                disc_config
            )
        
        # 2. 初始化 connection pool
        conn_config = ConnectionConfig(
            pool_size=50,
            heartbeat_interval=30.0,
            heartbeat_timeout=10.0,
            connect_timeout=5.0
        )
        self.connection_pool = create_connection_pool(conn_config)
        await self.connection_pool.start()
        
        # 3. 发现并连接到 bootstrap 节点（server）
        all_nodes = self.discovery_registry.get_all_nodes()
        bootstrap_nodes = [n for n in all_nodes if "bootstrap" in n.tags]
        
        if not bootstrap_nodes:
            logger.error(f"[{self.node_id}] No bootstrap nodes found in known_nodes.json")
            return
        
        logger.info(f"[{self.node_id}] Discovered {len(bootstrap_nodes)} bootstrap nodes")
        
        # 连接到第一个 bootstrap（server）
        bootstrap = bootstrap_nodes[0]
        await self.connection_pool.get_connection(bootstrap.node_id, bootstrap.address)
        logger.info(f"[{self.node_id}] Connected to bootstrap {bootstrap.node_id} @ {bootstrap.address}")
        
        # 4. 启动 client WebSocket（用于 incoming 消息）
        # 注意：这里我们需要一个 client 连接到 server，但 connection pool 已经建立了 outgoing 连接
        # 为了接收消息，我们还需要一个 client 实例吗？
        # 简化：我们这里只测试 connection pool 的 outgoing 发送能力
        # incoming 消息由 server 的 handle_peer_messages 处理，client 消息由 connection pool 处理

    async def send_message(self, to_node_id: str, content: str):
        """通过 connection pool 发送消息"""
        if not self.connection_pool:
            logger.error(f"[{self.node_id}] Connection pool not initialized")
            return False
        
        # 获取连接（从 registry 查地址）
        node_info = self.discovery_registry.get_node(to_node_id)
        if not node_info:
            logger.error(f"[{self.node_id}] Unknown node: {to_node_id}")
            return False
        
        # 获取或创建连接
        conn = await self.connection_pool.get_connection(to_node_id, node_info.address)
        
        # 构造消息（使用真实的 dataclass）
        from adapter.message import Message, MessagePayload, MessageRouting, MessageMeta
        msg = Message(
            meta=MessageMeta(
                node_id=self.node_id,
                timestamp=int(time.time()),
                protocol_version='1.0'
            ),
            payload=MessagePayload(type='text', content=content),
            routing=MessageRouting(to=to_node_id)
        )
        
        success = await conn.send(msg)
        if success:
            logger.info(f"[{self.node_id}] Sent message to {to_node_id}: {content}")
        else:
            logger.warning(f"[{self.node_id}] Failed to send message to {to_node_id}")
        return success

    async def broadcast(self, content: str):
        """广播消息"""
        if not self.connection_pool:
            logger.error(f"[{self.node_id}] Connection pool not initialized")
            return 0
        
        from adapter.message import Message, MessagePayload, MessageRouting, MessageMeta
        msg = Message(
            meta=MessageMeta(
                node_id=self.node_id,
                timestamp=int(time.time()),
                protocol_version='1.0'
            ),
            payload=MessagePayload(type='text', content=content),
            routing=MessageRouting(to='broadcast')
        )
        
        sent = await self.connection_pool.broadcast(msg)
        logger.info(f"[{self.node_id}] Broadcasted to {sent} nodes: {content}")
        return sent

    async def stop(self):
        """停止节点"""
        logger.info(f"[{self.node_id}] Stopping...")
        self._shutdown.set()
        
        # 停止所有任务
        for task in self._tasks:
            task.cancel()
        
        # 停止 connection pool
        if self.connection_pool:
            await self.connection_pool.stop()
        
        # 停止 UDP broadcaster
        if self.discovery_broadcaster:
            await self.discovery_broadcaster.stop()
        
        # 停止 server
        if self.server:
            self.server.shutdown_flag = True
            await asyncio.sleep(0.5)
        
        logger.info(f"[{self.node_id}] Stopped")

# ============== Demo Scenario ==============

async def run_multi_node_demo():
    """运行多节点演示"""
    
    print("\n" + "="*70)
    print("ClawMesh Phase 2 - Multi-Node Demo")
    print("="*70)
    
    project_root = Path(__file__).parent.parent
    
    # 生成节点 IDs
    node_a_id = "CL-01S-SERVER-001"
    node_b_id = "CL-01S-CLIENT-B"
    node_c_id = "CL-01S-CLIENT-C"
    
    logger.info(f"Node IDs: A={node_a_id}, B={node_b_id}, C={node_c_id}")
    
    # 创建 known_nodes.json 临时内容（包含所有节点）
    import json
    known_nodes = {
        "version": "1.0",
        "bootstrap": [
            {
                "node_id": node_a_id,
                "address": "ws://127.0.0.1:12448",
                "description": "Server node (A)",
                "tags": ["bootstrap", "server"]
            }
        ],
        "known_peers": [
            {
                "node_id": node_b_id,
                "address": "ws://127.0.0.1:12448",  # 也连接到 server
                "description": "Client node B",
                "tags": ["client"]
            },
            {
                "node_id": node_c_id,
                "address": "ws://127.0.0.1:12448",  # 也连接到 server
                "description": "Client node C",
                "tags": ["client"]
            }
        ]
    }
    config_dir = project_root / "config"
    config_dir.mkdir(exist_ok=True)
    known_nodes_file = config_dir / "known_nodes.json"
    with open(known_nodes_file, 'w') as f:
        json.dump(known_nodes, f, indent=2)
    logger.info(f"Created temporary known_nodes.json with bootstrap {node_a_id}")
    
    # 创建节点
    node_a = DemoNode(node_a_id, is_server=True)
    node_b = DemoNode(node_b_id, is_server=False, server_url="ws://127.0.0.1:12448")
    node_c = DemoNode(node_c_id, is_server=False, server_url="ws://127.0.0.1:12448")
    
    try:
        # 启动节点 A（server）
        await node_a.start_server(port=12448)
        await asyncio.sleep(1)
        
        # 启动节点 B 和 C（clients）
        await node_b.start_client(project_root)
        await node_c.start_client(project_root)
        await asyncio.sleep(2)  # 等待发现和连接
        
        # 检查连接池状态
        stats_b = node_b.connection_pool.get_connection_stats()
        stats_c = node_c.connection_pool.get_connection_stats()
        logger.info(f"Node B pool: {stats_b['online']}/{stats_b['total_connections']} online")
        logger.info(f"Node C pool: {stats_c['online']}/{stats_c['total_connections']} online")
        
        # 等待所有连接建立（最多 10 秒）
        for _ in range(10):
            if stats_b['online'] > 0 and stats_c['online'] > 0:
                break
            await asyncio.sleep(1)
            stats_b = node_b.connection_pool.get_connection_stats()
            stats_c = node_c.connection_pool.get_connection_stats()
        
        if stats_b['online'] == 0 or stats_c['online'] == 0:
            logger.error("Failed to establish connections")
            return False
        
        print("\n" + "="*70)
        print("Phase 2: Broadcast")
        print("="*70)
        
        # Test: B broadcasts to all (including C via server)
        logger.info("Test: Node B broadcasting to all peers")
        sent = await node_b.broadcast("Broadcast from B to everyone!")
        if sent < 1:
            logger.warning(f"Broadcast sent to {sent} nodes (unexpected)")
        await asyncio.sleep(1)
        
        # Also test C broadcasting
        logger.info("Test: Node C broadcasting to all peers")
        sent = await node_c.broadcast("Hello from C!")
        await asyncio.sleep(1)
        
        print("\n" + "="*70)
        print("Phase 3: Disconnection and reconnection")
        print("="*70)
        
        # Test 4: Simulate node C "offline" by stopping its client
        logger.info("Test 4: Stopping Node C to simulate offline")
        await node_c.stop()
        await asyncio.sleep(1)
        
        # Check B's pool status: C should be offline
        stats_b = node_b.connection_pool.get_connection_stats()
        logger.info(f"Node B pool after C offline: {stats_b['online']} online, {stats_b['offline']} offline")
        
        # Test 5: Restart Node C (reconnect)
        logger.info("Test 5: Restarting Node C (should reconnect)")
        node_c = DemoNode(node_c_id, is_server=False, server_url="ws://127.0.0.1:12448")
        await node_c.start_client(project_root)
        await asyncio.sleep(3)  # 等待重连
        
        stats_b = node_b.connection_pool.get_connection_stats()
        stats_c = node_c.connection_pool.get_connection_stats()
        logger.info(f"After C reconnected: B={stats_b['online']} online, C={stats_c['online']} online")
        
        if stats_c['online'] > 0:
            logger.info("Node C reconnected successfully!")
            # Test 6: Send message again
            await node_b.send_message(node_c_id, "Welcome back, C!")
            await asyncio.sleep(1)
        else:
            logger.warning("Node C did not reconnect within timeout")
        
        print("\n" + "="*70)
        print("Demo Complete!")
        print("="*70)
        logger.info("All tests completed. Shutting down...")
        
        return True
        
    except Exception as e:
        logger.error(f"Demo failed: {e}", exc_info=True)
        return False
    finally:
        # Cleanup
        logger.info("Cleaning up nodes...")
        await asyncio.gather(
            node_a.stop(),
            node_b.stop(),
            node_c.stop(),
            return_exceptions=True
        )
        
        # 删除临时 known_nodes.json
        try:
            if known_nodes_file.exists():
                known_nodes_file.unlink()
        except:
            pass

if __name__ == "__main__":
    try:
        success = asyncio.run(run_multi_node_demo())
        if success:
            print("\n[SUCCESS] Multi-node demo completed successfully!")
            sys.exit(0)
        else:
            print("\n[FAILED] Multi-node demo had errors")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n[INTERRUPT] Demo cancelled by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n[ERROR] Demo crashed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
