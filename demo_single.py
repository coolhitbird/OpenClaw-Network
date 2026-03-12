"""
ClawMesh Phase 1 - Single Window Demo

All-in-one demo: starts server, then two clients sequentially in same process.
All logs output to same console for easy debugging.
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

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from adapter.node_id import generate_node_id
from node.server import ClawMeshServer
from node.client import ClawMeshClient

async def run_single_window_demo():
    """Single window demo: server + clients in same event loop"""

    print("=" * 60)
    print("ClawMesh Phase 1 - Single Window Demo")
    print("=" * 60)

    # Step 1: Start server as background task
    print("\n[1] Starting server on 127.0.0.1:8765...")
    server = ClawMeshServer(host="127.0.0.1", port=8765)
    server_task = asyncio.create_task(server.start())
    await asyncio.sleep(2)  # Wait for server to bind

    if server_task.done():
        print("[FAIL] Server task finished unexpectedly")
        try:
            await server_task
        except Exception as e:
            print(f"[ERROR] Server crashed: {e}")
        return False

    print("[OK] Server is running")

    try:
        # Step 2: Create two nodes
        print("\n[2] Generating node IDs...")
        node_a = generate_node_id('S')
        node_b = generate_node_id('S')
        print(f"  Node A: {node_a}")
        print(f"  Node B: {node_b}")

        # Step 3: Connect clients
        print("\n[3] Connecting clients...")
        client_a = ClawMeshClient(node_a, "ws://127.0.0.1:8765")
        client_b = ClawMeshClient(node_b, "ws://127.0.0.1:8765")

        # Start connection tasks (they run forever until shutdown)
        tasks = [
            asyncio.create_task(client_a.connect(), name="ClientA"),
            asyncio.create_task(client_b.connect(), name="ClientB")
        ]

        # Wait for connections to establish
        await asyncio.sleep(3)

        # Debug: check websocket states
        print(f"\n[DEBUG] Client A: websocket={client_a.websocket}, closed={getattr(client_a.websocket, 'closed', 'N/A')}, connected={client_a.connected.is_set()}")
        print(f"[DEBUG] Client B: websocket={client_b.websocket}, closed={getattr(client_b.websocket, 'closed', 'N/A')}, connected={client_b.connected.is_set()}")

        if not (client_a.connected.is_set() and client_b.connected.is_set()):
            print("[FAIL] Not all clients connected")
            print(f"  Client A connected: {client_a.connected.is_set()}")
            print(f"  Client B connected: {client_b.connected.is_set()}")
            return False

        print("[OK] Both clients connected and handshake completed")

        # Step 4: Test communications
        print("\n[4] Testing broadcast from Node A...")
        await client_a.broadcast("Hello from Node A!")
        await asyncio.sleep(1)

        print("[5] Testing direct message from Node B to Node A...")
        await client_b.send_message(node_a, "Hi A, this is B.")
        await asyncio.sleep(1)

        print("[6] Testing direct message from Node A to Node B...")
        await client_a.send_message(node_b, "Hi B, this is A.")
        await asyncio.sleep(1)

        print("\n" + "=" * 60)
        print("[SUCCESS] All tests passed!")
        print("=" * 60)
        return True

    finally:
        # Cleanup
        print("\n[Cleanup] Shutting down...")
        if 'client_a' in locals():
            client_a.shutdown = True
        if 'client_b' in locals():
            client_b.shutdown = True
        server.shutdown_flag = True

        # Wait a moment for cleanup
        await asyncio.sleep(1)
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
        for t in tasks:
            t.cancel()
        print("[OK] Cleanup completed")

if __name__ == "__main__":
    try:
        success = asyncio.run(run_single_window_demo())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n[INTERRUPT] Demo cancelled by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n[ERROR] Demo failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
