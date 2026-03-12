"""
Phase 2 Integration Test - Core Components

测试 discovery + connection 关键集成点，不包含完整 server/client 流程。
Focus: NodeRegistry + ConnectionPool interaction.

Run: uv run python tests/test_phase2_integration.py
"""

import sys
import asyncio
import time
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from adapter.discovery import (
    KnownNodesLoader, UDPBroadcaster, NodeRegistry, DiscoveryConfig,
    NodeInfo, create_discovery_components
)
from adapter.connection import (
    ConnectionPool, ConnectionConfig, OutgoingConnection,
    ConnectionState
)

async def test_discovery_connection_integration():
    """测试 discovery 提供节点信息，connection pool 建立连接"""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        known_file = config_dir / "known_nodes.json"
        
        # 创建测试配置
        nodes = [
            {"node_id": "CL-01S-A", "address": "ws://127.0.0.1:12448", "tags": ["bootstrap"]},
            {"node_id": "CL-01S-B", "address": "ws://127.0.0.1:12449", "tags": ["peer"]}
        ]
        with open(known_file, 'w') as f:
            json.dump({"bootstrap": nodes, "known_peers": []}, f)
        
        disc_config = DiscoveryConfig(known_nodes_file=str(known_file), enabled=False)
        loader = KnownNodesLoader(disc_config)
        await loader.load(tmp_path)
        
        # 创建 discovery 组件（无 UDP）
        broadcaster = UDPBroadcaster(disc_config, "CL-01S-TEST") if disc_config.enabled else None
        registry = NodeRegistry(loader, broadcaster, disc_config)
        
        # 验证 registry 返回预设节点
        all_nodes = registry.get_all_nodes()
        assert len(all_nodes) == 2
        node_map = {n.node_id: n for n in all_nodes}
        assert "CL-01S-A" in node_map
        assert node_map["CL-01S-A"].address == "ws://127.0.0.1:12448"
        
        # 创建 connection pool
        pool = ConnectionPool()
        await pool.start()
        
        try:
            # 模拟 OutgoingConnection 的 connect 成功
            from unittest.mock import patch, AsyncMock, MagicMock
            
            # 创建一个 mock websocket
            def create_mock_ws():
                mock = MagicMock()
                mock.closed = False
                mock.state = 1  # OPEN
                mock.close = MagicMock()
                return mock
            
            async def mock_connect_success(self):
                self.websocket = create_mock_ws()
                self.state = ConnectionState.ONLINE
                self.last_seen = time.time()
                self.successful_connections += 1
                return True
            
            with patch.object(OutgoingConnection, 'connect', new=mock_connect_success):
                # 获取连接（会创建新的 OutgoingConnection）
                conn = await pool.get_connection("CL-01S-A", "ws://127.0.0.1:12448")
                assert conn.node_id == "CL-01S-A"
                assert conn.address == "ws://127.0.0.1:12448"
                assert conn in pool._connections.values()
                
                # 验证连接池统计
                stats = pool.get_connection_stats()
                assert stats['total_connections'] == 1
                assert stats['online'] == 1
                
                # 测试获取同一连接（应复用）
                conn2 = await pool.get_connection("CL-01S-A", "ws://127.0.0.1:12448")
                assert conn is conn2, "Should reuse existing connection"
                
                # 测试添加第二个连接
                conn_b = await pool.get_connection("CL-01S-B", "ws://127.0.0.1:12449")
                assert conn_b.node_id == "CL-01S-B"
                stats = pool.get_connection_stats()
                assert stats['total_connections'] == 2
                
                # 测试 LRU 驱逐（达到 pool_size）
                small_pool = ConnectionPool(ConnectionConfig(pool_size=2))
                await small_pool.start()
                try:
                    # 添加两个连接
                    await small_pool.get_connection("CL-01S-1", "ws://1:12448")
                    await small_pool.get_connection("CL-01S-2", "ws://2:12448")
                    assert len(small_pool._connections) == 2
                    
                    # 添加第三个（应触发驱逐）
                    await small_pool.get_connection("CL-01S-3", "ws://3:12448")
                    await asyncio.sleep(0.1)  # 让 _evict_lru 执行
                    assert len(small_pool._connections) == 2, "LRU: pool should not exceed max_size"
                finally:
                    await small_pool.stop()
                
                print("[OK] Discovery + Connection integration")
                return True
                
        finally:
            await pool.stop()

async def test_connection_retry_policy():
    """测试重试策略计算"""
    config = ConnectionConfig(retry_initial_interval=5.0, retry_max_initial=3)
    
    conn = OutgoingConnection("CL-01S-TEST", "ws://localhost:12448", config)
    
    # 前 3 次应为指数退避
    conn.retry_count = 0
    assert conn._compute_backoff() == 5.0
    conn.retry_count = 1
    assert conn._compute_backoff() == 10.0
    conn.retry_count = 2
    assert conn._compute_backoff() == 20.0
    
    # 第 4 次应为每小时
    conn.retry_count = 3
    assert conn._compute_backoff() == 3600.0
    
    # test _should_retry
    conn.retry_count = 0
    assert conn._should_retry() is True
    conn.retry_count = 2
    assert conn._should_retry() is True
    conn.retry_count = 5
    assert conn._should_retry() is False  # 超过 max_initial 且不是每小时
    
    # 模拟 1 小时后的重试
    conn.last_attempt = time.time() - 3700  # 1 小时前
    conn.retry_count = 5
    assert conn._should_retry() is True
    
    print("[OK] Connection retry policy")
    return True

# ============== Main ==============

if __name__ == "__main__":
    print("Running Phase 2 integration tests...\n")
    
    success = True
    
    try:
        asyncio.run(test_discovery_connection_integration())
    except Exception as e:
        print(f"[FAILED] test_discovery_connection_integration: {e}")
        import traceback
        traceback.print_exc()
        success = False
    
    try:
        asyncio.run(test_connection_retry_policy())
    except Exception as e:
        print(f"[FAILED] test_connection_retry_policy: {e}")
        success = False
    
    if success:
        print("\n[SUCCESS] All Phase 2 integration tests passed!")
        sys.exit(0)
    else:
        sys.exit(1)
