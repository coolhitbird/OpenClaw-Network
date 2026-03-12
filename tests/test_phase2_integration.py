"""
Phase 2 Integration Test - Discovery + Connection Pool

测试场景：
1. 启动 WebSocket server (Node A)
2. 创建 Node B 和 Node C，使用 discovery 发现 A
3. B 和 C 通过 connection pool 连接到 A
4. 验证连接状态、广播功能、重连机制

运行: uv run python tests/test_phase2_integration.py
"""

import sys
import asyncio
import time
import json
import tempfile
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).parent.parent))

from adapter.node_id import generate_node_id
from node.server import ClawMeshServer
from adapter.discovery import (
    KnownNodesLoader, UDPBroadcaster, NodeRegistry, DiscoveryConfig,
    create_discovery_components
)
from adapter.connection import (
    ConnectionPool, ConnectionConfig, create_connection_pool
)
from adapter.message import Message, MessagePayload, MessageRouting, MessageMeta

class TestNode:
    """测试节点：包含 discovery + connection pool + client"""
    
    def __init__(self, node_id: str, role: str = "client"):
        self.node_id = node_id
        self.role = role  # "server" or "client"
        self.server: Optional[ClawMeshServer] = None
        self.discovery_loader: Optional[KnownNodesLoader] = None
        self.discovery_broadcaster: Optional[UDPBroadcaster] = None
        self.discovery_registry: Optional[NodeRegistry] = None
        self.connection_pool: Optional[ConnectionPool] = None
        self._tasks: List[asyncio.Task] = []
        self._shutdown = asyncio.Event()
    
    async def start_server(self, host: str = "127.0.0.1", port: int = 12448):
        """启动 server 模式"""
        self.server = ClawMeshServer(host=host, port=port)
        self.server_task = asyncio.create_task(self.server.start())
        await asyncio.sleep(0.5)  # 等待绑定
    
    async def start_client(self, project_root: Path, bootstrap_port: int = 12448):
        """启动 client 模式"""
        # 创建临时 known_nodes.json
        config_dir = project_root / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        known_file = config_dir / "known_nodes.json"
        
        # 写入当前测试的 bootstrap 信息（需要主测试函数填充）
        # 实际内容由主测试函数写入
        
        # 初始化 discovery（不使用 UDP，避免端口冲突）
        disc_config = DiscoveryConfig(
            known_nodes_file="config/known_nodes.json",
            enabled=False  # 关闭 UDP 广播
        )
        self.discovery_loader = KnownNodesLoader(disc_config)
        await self.discovery_loader.load(project_root)
        
        self.discovery_registry = NodeRegistry(
            self.discovery_loader,
            None,  # 无 UDP broadcaster
            disc_config
        )
        
        # 初始化 connection pool
        conn_config = ConnectionConfig(
            pool_size=50,
            heartbeat_interval=30.0,
            heartbeat_timeout=10.0,
            connect_timeout=5.0
        )
        self.connection_pool = create_connection_pool(conn_config)
        await self.connection_pool.start()
    
    async def connect_to_bootstrap(self, node_id: str, address: str):
        """连接到指定的 bootstrap 节点"""
        conn = await self.connection_pool.get_connection(node_id, address)
        return conn
    
    def get_online_count(self) -> int:
        """获取连接池中在线连接数"""
        if not self.connection_pool:
            return 0
        stats = self.connection_pool.get_connection_stats()
        return stats['online']
    
    async def broadcast(self, content: str) -> int:
        """广播消息"""
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
        return sent
    
    async def stop(self):
        """停止节点"""
        self._shutdown.set()
        if self.connection_pool:
            await self.connection_pool.stop()
        if self.server:
            self.server.shutdown_flag = True
            await asyncio.sleep(0.2)
        for task in self._tasks:
            task.cancel()
        # 清理临时文件
        # ...

# ============== Test Cases ==============

async def test_three_node_network():
    """测试 3 节点网络：A(server) + B(client) + C(client)"""
    
    print("\n" + "="*70)
    print("Phase 2 Integration Test: 3-Node Network")
    print("="*70)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        project_root = tmp_path / "project"
        project_root.mkdir()
        config_dir = project_root / "config"
        config_dir.mkdir()
        
        # 生成节点 IDs
        node_a_id = "CL-01S-TEST-A"
        node_b_id = "CL-01S-TEST-B"
        node_c_id = "CL-01S-TEST-C"
        
        # 创建 known_nodes.json
        known_nodes = {
            "version": "1.0",
            "bootstrap": [
                {"node_id": node_a_id, "address": "ws://127.0.0.1:12448", "tags": ["bootstrap"]},
                {"node_id": node_b_id, "address": "ws://127.0.0.1:12448", "tags": ["peer"]},
                {"node_id": node_c_id, "address": "ws://127.0.0.1:12448", "tags": ["peer"]}
            ],
            "known_peers": []
        }
        known_file = config_dir / "known_nodes.json"
        with open(known_file, 'w') as f:
            json.dump(known_nodes, f, indent=2)
        
        # 创建节点
        node_a = TestNode(node_a_id, role="server")
        node_b = TestNode(node_b_id, role="client")
        node_c = TestNode(node_c_id, role="client")
        
        try:
            # 启动 Node A (server)
            print("[1/6] Starting server (Node A)...")
            await node_a.start_server(port=12448)
            
            # 启动 Node B
            print("[2/6] Starting client (Node B)...")
            await node_b.start_client(project_root)
            
            # 连接 Node B 到 A
            await node_b.connect_to_bootstrap(node_a_id, "ws://127.0.0.1:12448")
            await asyncio.sleep(0.5)
            
            # 启动 Node C
            print("[3/6] Starting client (Node C)...")
            await node_c.start_client(project_root)
            
            # 连接 Node C 到 A
            await node_c.connect_to_bootstrap(node_a_id, "ws://127.0.0.1:12448")
            await asyncio.sleep(1)
            
            # 验证连接状态
            b_online = node_b.get_online_count()
            c_online = node_c.get_online_count()
            print(f"[4/6] Connection status: B={b_online} online, C={c_online} online")
            assert b_online >= 1, "Node B should have at least 1 online connection"
            assert c_online >= 1, "Node C should have at least 1 online connection"
            
            # 测试广播
            print("[5/6] Testing broadcast...")
            # B 广播
            sent_b = await node_b.broadcast("Hello from B")
            assert sent_b >= 1, f"B broadcast should reach at least 1 node, got {sent_b}"
            await asyncio.sleep(0.5)
            
            # C 广播
            sent_c = await node_c.broadcast("Hello from C")
            assert sent_c >= 1, f"C broadcast should reach at least 1 node, got {sent_c}"
            await asyncio.sleep(0.5)
            
            # 测试重连：停止 Node B 再重启
            print("[6/6] Testing reconnection...")
            await node_b.stop()
            await asyncio.sleep(1)
            
            # 重新启动 B
            node_b = TestNode(node_b_id, role="client")
            await node_b.start_client(project_root)
            await node_b.connect_to_bootstrap(node_a_id, "ws://127.0.0.1:12448")
            await asyncio.sleep(2)
            
            b_online_after = node_b.get_online_count()
            assert b_online_after >= 1, "Node B should reconnect successfully"
            print(f"After reconnection: B={b_online_after} online")
            
            print("\n" + "="*70)
            print("[SUCCESS] All integration tests passed!")
            print("="*70)
            return True
            
        except AssertionError as e:
            print(f"\n[FAILED] Assertion failed: {e}")
            return False
        except Exception as e:
            print(f"\n[ERROR] Test failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            # Cleanup
            await asyncio.gather(
                node_a.stop(),
                node_b.stop(),
                node_c.stop(),
                return_exceptions=True
            )

async def test_discovery_loader():
    """测试 KnownNodesLoader 加载和热重载"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        known_file = config_dir / "known_nodes.json"
        
        # 写入初始数据
        data = {
            "bootstrap": [{"node_id": "CL-01S-001", "address": "ws://localhost:12448"}],
            "known_peers": []
        }
        with open(known_file, 'w') as f:
            json.dump(data, f)
        
        config = DiscoveryConfig(known_nodes_file=str(known_file))
        loader = KnownNodesLoader(config)
        
        # 首次加载
        success = await loader.load(tmp_path)
        assert success is True
        assert loader.has_preset("CL-01S-001")
        assert len(loader.list_presets()) == 1
        
        # 热重载（修改文件）
        data["bootstrap"].append({"node_id": "CL-01S-002", "address": "ws://localhost:12449"})
        with open(known_file, 'w') as f:
            json.dump(data, f)
        
        reloaded = await loader.check_reload(tmp_path)
        assert reloaded is True
        assert loader.has_preset("CL-01S-002")
        assert len(loader.list_presets()) == 2
        
        print("[OK] Discovery loader and hot-reload")
        return True

# ============== Main ==============

if __name__ == "__main__":
    print("Running Phase 2 integration tests...\n")
    
    # 测试 1: discovery loader
    try:
        asyncio.run(test_discovery_loader())
    except Exception as e:
        print(f"[FAILED] test_discovery_loader: {e}")
        sys.exit(1)
    
    # 测试 2: 3-node network
    try:
        success = asyncio.run(test_three_node_network())
        if not success:
            sys.exit(1)
    except Exception as e:
        print(f"[FAILED] test_three_node_network: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    print("\n[SUCCESS] All Phase 2 integration tests passed!")
    sys.exit(0)
