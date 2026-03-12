"""
Unit tests for adapter/discovery.py

Run: uv run python tests/test_discovery.py
"""

import sys
import os
import json
import time
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from adapter.discovery import (
    NodeInfo,
    DiscoveryConfig,
    KnownNodesLoader,
    UDPBroadcaster,
    NodeRegistry,
    create_discovery_components
)

def test_node_info_dataclass():
    """测试 NodeInfo 数据类"""
    node = NodeInfo(
        node_id="CL-01S-test123",
        address="ws://localhost:8765",
        description="Test node",
        tags=["test", "local"],
        source="preset"
    )
    assert node.node_id == "CL-01S-test123"
    assert node.address == "ws://localhost:8765"
    assert node.source == "preset"
    assert node.last_seen is not None
    
    d = node.to_dict()
    assert d["node_id"] == "CL-01S-test123"
    assert d["tags"] == ["test", "local"]
    print("[OK] NodeInfo dataclass")

def test_discovery_config_defaults():
    """测试配置默认值"""
    config = DiscoveryConfig()
    assert config.enabled is True
    assert config.udp_port == 9876
    assert config.broadcast_interval == 30.0
    assert config.conflict_resolution == "preset_priority"
    assert config.known_nodes_file == "config/known_nodes.json"
    print("[OK] DiscoveryConfig defaults")

async def test_loader_loads_valid_json():
    """测试加载有效的 known_nodes.json"""
    with TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        config_file = tmp_path / "config" / "known_nodes.json"
        config_file.parent.mkdir(parents=True)
        
        data = {
            "bootstrap": [
                {
                    "node_id": "CL-01S-001",
                    "address": "ws://localhost:8765",
                    "description": "Local node",
                    "tags": ["bootstrap"]
                }
            ],
            "known_peers": [
                {
                    "node_id": "CL-01B-002",
                    "address": "ws://localhost:8766",
                    "tags": ["bot"]
                }
            ]
        }
        with open(config_file, 'w') as f:
            json.dump(data, f)
        
        loader = KnownNodesLoader(DiscoveryConfig(known_nodes_file=str(config_file)))
        success = await loader.load(tmp_path)
        assert success is True
        assert len(loader.presets) == 2
        assert loader.has_preset("CL-01S-001")
        assert loader.has_preset("CL-01B-002")
        
        preset = loader.get_preset("CL-01S-001")
        assert preset.address == "ws://localhost:8765"
        assert "bootstrap" in preset.tags
        print("[OK] Loader loads valid JSON")

async def test_loader_handles_missing_file():
    """测试文件不存在的情况"""
    with TemporaryDirectory() as tmpdir:
        loader = KnownNodesLoader(DiscoveryConfig(known_nodes_file="nonexistent.json"))
        success = await loader.load(Path(tmpdir))
        assert success is False
        assert len(loader.presets) == 0
        print("[OK] Loader handles missing file")

async def test_loader_handles_invalid_json():
    """测试 JSON 格式错误"""
    with TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "known_nodes.json"
        config_file.write_text("{ invalid json }", encoding='utf-8')
        
        loader = KnownNodesLoader(DiscoveryConfig(known_nodes_file=str(config_file)))
        success = await loader.load(tmp_path)
        assert success is False
        print("[OK] Loader handles invalid JSON")

def test_node_registry_preset_priority():
    """测试注册表：预设优先于 UDP"""
    # 创建 mock 组件
    class MockLoader:
        def __init__(self):
            self.presets = {
                "CL-01S-A": NodeInfo("CL-01S-A", "ws://preset:8765", source="preset")
            }
        def list_presets(self):
            return list(self.presets.values())
        def get_preset(self, node_id):
            return self.presets.get(node_id)
        def has_preset(self, node_id):
            return node_id in self.presets
    
    class MockDiscovery:
        def get_discovered(self, ttl=None):
            return {
                "CL-01S-A": NodeInfo("CL-01S-A", "ws://udp:9876", source="udp", last_seen=time.time()),
                "CL-01S-B": NodeInfo("CL-01S-B", "ws://udp:9876", source="udp", last_seen=time.time())
            }
    
    config = DiscoveryConfig()
    registry = NodeRegistry(MockLoader(), MockDiscovery(), config)
    all_nodes = registry.get_all_nodes()
    
    # 检查结果
    node_map = {n.node_id: n for n in all_nodes}
    assert "CL-01S-A" in node_map
    assert node_map["CL-01S-A"].source == "preset"  # 预设优先
    assert node_map["CL-01S-A"].address == "ws://preset:8765"
    assert "CL-01S-B" in node_map
    assert node_map["CL-01S-B"].source == "udp"
    
    # 检查冲突日志
    conflicts = registry.get_conflicts()
    assert len(conflicts) == 1
    assert conflicts[0]["node_id"] == "CL-01S-A"
    assert conflicts[0]["preset_address"] == "ws://preset:8765"
    assert conflicts[0]["udp_address"] == "ws://udp:9876"
    
    print("[OK] NodeRegistry preset priority")

def test_node_registry_no_duplicates():
    """测试注册表不会重复添加同一节点"""
    class MockLoader:
        def __init__(self):
            self.presets = {
                "CL-01S-A": NodeInfo("CL-01S-A", "ws://preset:8765", source="preset")
            }
        def list_presets(self):
            return list(self.presets.values())
        def get_preset(self, node_id):
            return self.presets.get(node_id)
        def has_preset(self, node_id):
            return node_id in self.presets
    
    class MockDiscovery:
        def get_discovered(self, ttl=None):
            return {
                "CL-01S-A": NodeInfo("CL-01S-A", "ws://udp:9876", source="udp", last_seen=time.time())
            }
    
    config = DiscoveryConfig()
    registry = NodeRegistry(MockLoader(), MockDiscovery(), config)
    all_nodes = registry.get_all_nodes()
    assert len(all_nodes) == 1  # 只有预设，UDP 的副本被忽略
    print("[OK] No duplicate nodes when preset exists")

async def test_discovery_components_creation():
    """测试工厂函数创建组件"""
    with TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        # 创建 config 目录和示例文件
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        known_file = config_dir / "known_nodes.json"
        known_file.write_text('{"bootstrap": [], "known_peers": []}', encoding='utf-8')
        
        loader, broadcaster, registry = create_discovery_components(
            project_root=tmp_path,
            own_node_id="CL-01S-TEST",
            config=DiscoveryConfig()
        )
        assert isinstance(loader, KnownNodesLoader)
        assert isinstance(broadcaster, UDPBroadcaster)
        assert isinstance(registry, NodeRegistry)
        assert broadcaster.own_node_id == "CL-01S-TEST"
        print("[OK] Discovery components creation")

# ============== Main ==============

if __name__ == "__main__":
    print("Running discovery tests...\n")
    
    # 同步测试
    test_node_info_dataclass()
    test_discovery_config_defaults()
    test_node_registry_preset_priority()
    test_node_registry_no_duplicates()
    
    # 异步测试
    asyncio.run(test_loader_loads_valid_json())
    asyncio.run(test_loader_handles_missing_file())
    asyncio.run(test_loader_handles_invalid_json())
    asyncio.run(test_discovery_components_creation())
    
    print("\n[SUCCESS] All discovery tests passed!")
