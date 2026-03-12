"""
OpenClaw Network - ClawMesh Demo Script (Phase 1)

演示两个节点如何通信：
1. 启动 server (在后台任务)
2. 启动两个 client 节点
3. Client A 发送 broadcast → Server 转发给 Client B
4. Client B 发送 direct message → Server 转发给 Client A

运行: uv run python examples/demo.py

要求: 先在一个终端运行: uv run python node/server.py
然后在另一个终端运行: uv run python examples/demo.py
"""

import asyncio
import sys
import logging
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from adapter.node_id import generate_node_id
from node.client import ClawMeshClient

async def run_demo(server_url: str):
    """运行演示"""

    # 生成两个节点 ID
    node_a = generate_node_id('S')
    node_b = generate_node_id('S')
    logger.info(f"Node A: {node_a}")
    logger.info(f"Node B: {node_b}")

    # 创建两个客户端
    client_a = ClawMeshClient(node_a, server_url)
    client_b = ClawMeshClient(node_b, server_url)

    # 并发启动连接
    tasks = [
        asyncio.create_task(client_a.connect(), name="ClientA"),
        asyncio.create_task(client_b.connect(), name="ClientB")
    ]

    # 等待连接建立
    await asyncio.sleep(2)

    # 检查连接状态
    if not (client_a.connected.is_set() and client_b.connected.is_set()):
        logger.error("One or both clients failed to connect")
        client_a.shutdown = True
        client_b.shutdown = True
        for t in tasks:
            t.cancel()
        return

    logger.info("Both nodes connected. Starting communication demo.")

    # Test 1: Client A broadcast
    logger.info("\n=== Test 1: Broadcast from Node A ===")
    await client_a.broadcast("Hello from Node A!")
    await asyncio.sleep(1)

    # Test 2: Client B send direct message to A
    logger.info("\n=== Test 2: Direct message from Node B to Node A ===")
    await client_b.send_message(node_a, "Hi Node A, this is Node B.")
    await asyncio.sleep(1)

    # Test 3: Client A send direct message to B
    logger.info("\n=== Test 3: Direct message from Node A to Node B ===")
    await client_a.send_message(node_b, "Reply from Node A to B.")
    await asyncio.sleep(1)

    # 完成
    logger.info("\n=== Demo complete ===")
    logger.info("Shutting down clients...")
    client_a.shutdown = True
    client_b.shutdown = True
    await asyncio.gather(*tasks, return_exceptions=True)

if __name__ == "__main__":
    import argparse
    import logging

    # 设置日志级别
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    parser = argparse.ArgumentParser(description="ClawMesh Demo")
    parser.add_argument("--server", default="ws://localhost:8765", help="WebSocket server URL")
    args = parser.parse_args()

    try:
        asyncio.run(run_demo(args.server))
    except KeyboardInterrupt:
        print("\nDemo interrupted")
    except Exception as e:
        print(f"Demo failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
