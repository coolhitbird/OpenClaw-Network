"""
Integration Test for ClawMesh Phase 1

自动测试：
1. 启动 WebSocket server 在后台
2. 创建两个 client 节点
3. 验证 handshake 成功
4. 测试 broadcast 和 direct message
5. 清理资源

运行: uv run python tests/test_integration.py
"""

import asyncio
import sys
import time
from pathlib import Path

# 添加路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from adapter.node_id import generate_node_id
from node.server import ClawMeshServer
from node.client import ClawMeshClient

async def test_basic_communication():
    """基础通信测试"""

    # 启动 server
    server = ClawMeshServer(host="127.0.0.1", port=9876)
    server_task = asyncio.create_task(server.start())

    # 等待 server 启动
    await asyncio.sleep(1)

    # 生成两个节点
    node_a = generate_node_id('S')
    node_b = generate_node_id('S')
    print(f"Node A: {node_a}")
    print(f"Node B: {node_b}")

    # 创建 client A 和 B
    client_a = ClawMeshClient(node_a, "ws://127.0.0.1:9876")
    client_b = ClawMeshClient(node_b, "ws://127.0.0.1:9876")

    # 连接
    tasks = [
        asyncio.create_task(client_a.connect()),
        asyncio.create_task(client_b.connect())
    ]
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)

    assert client_a.connected.is_set(), "Client A not connected"
    assert client_b.connected.is_set(), "Client B not connected"
    print("[OK] Both clients connected")

    # 等待 handshake ack 被处理
    await asyncio.sleep(0.5)

    # 测试：Client A broadcast
    await client_a.broadcast("Hello from A")
    await asyncio.sleep(0.5)

    # 测试：Client B 发送 direct message 给 A
    await client_b.send_message(node_a, "Hi A, from B")
    await asyncio.sleep(0.5)

    # 测试：Client A 发送 direct message 给 B
    await client_a.send_message(node_b, "Hi B, from A")
    await asyncio.sleep(0.5)

    # 清理
    client_a.shutdown = True
    client_b.shutdown = True
    server.shutdown_flag = True

    # 等待任务结束
    await asyncio.wait([server_task] + tasks, timeout=3)

    print("[OK] Test completed successfully")

if __name__ == "__main__":
    try:
        asyncio.run(test_basic_communication())
        print("\n[SUCCESS] All integration tests passed!")
    except AssertionError as e:
        print(f"\n[FAILED] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
