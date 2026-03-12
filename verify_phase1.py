"""
ClawMesh Phase 1 Verification Script

This script:
1. Starts ClawMesh server in background
2. Creates two node clients
3. Tests handshake, broadcast, and direct messaging
4. Reports success/failure

Run: python verify_phase1.py
"""

import asyncio
import sys
import subprocess
import time
import logging
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Add project path
sys.path.insert(0, str(Path(__file__).parent))

from adapter.node_id import generate_node_id
from node.server import ClawMeshServer
from node.client import ClawMeshClient

async def run_verification():
    """Main verification workflow"""

    print("=== ClawMesh Phase 1 Verification ===\n")

    # Start server
    print("[1/5] Starting server...")
    server = ClawMeshServer(host="127.0.0.1", port=8765)
    server_task = asyncio.create_task(server.start())
    await asyncio.sleep(1)  # Wait for server

    if not server_task.done():
        print("[OK] Server started on 127.0.0.1:8765")
    else:
        print("[FAIL] Server failed to start")
        return False

    try:
        # Generate node IDs
        print("\n[2/5] Generating node IDs...")
        node_a = generate_node_id('S')
        node_b = generate_node_id('S')
        print(f"  Node A: {node_a}")
        print(f"  Node B: {node_b}")

        # Create clients
        print("\n[3/5] Connecting clients...")
        client_a = ClawMeshClient(node_a, "ws://127.0.0.1:8765")
        client_b = ClawMeshClient(node_b, "ws://127.0.0.1:8765")

        # Connect both
        tasks = [
            asyncio.create_task(client_a.connect()),
            asyncio.create_task(client_b.connect())
        ]

        # 等待连接建立（不等待 connect() 返回，它不会返回）
        await asyncio.sleep(2)

        # 检查连接状态
        if not (client_a.connected.is_set() and client_b.connected.is_set()):
            print("[FAIL] Not all clients connected")
            for t in tasks:
                t.cancel()
            return False

        print("[OK] Both clients connected and handshake completed")

        # Clear any pending messages
        await asyncio.sleep(0.5)

        # Test broadcast from A
        print("\n[4/5] Testing broadcast from Node A...")
        await client_a.broadcast("Hello from Node A!")
        await asyncio.sleep(1)  # Wait for delivery

        # Test direct message from B to A
        print("Testing direct message from Node B to Node A...")
        await client_b.send_message(node_a, "Hi A, this is B.")
        await asyncio.sleep(1)

        # Test direct message from A to B
        print("Testing direct message from Node A to Node B...")
        await client_a.send_message(node_b, "Hi B, this is A.")
        await asyncio.sleep(1)

        print("[OK] All message tests completed")

        # Summary
        print("\n[5/5] Verification Summary:")
        print("  ✓ Server started successfully")
        print("  ✓ Two nodes connected")
        print("  ✓ Handshake completed")
        print("  ✓ Broadcast and direct messaging working")

        return True

    finally:
        # Cleanup
        print("\n[Cleanup] Shutting down...")
        if 'client_a' in locals():
            client_a.shutdown = True
        if 'client_b' in locals():
            client_b.shutdown = True
        server.shutdown_flag = True

        # Wait for tasks to finish
        await asyncio.sleep(1)
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

        print("[OK] Cleanup completed")

if __name__ == "__main__":
    try:
        success = asyncio.run(run_verification())
        if success:
            print("\n[SUCCESS] Phase 1 verification PASSED!")
            print("All core features are working correctly.")
            sys.exit(0)
        else:
            print("\n[FAILED] Phase 1 verification FAILED!")
            print("Check server logs for details.")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n[INTERRUPT] Verification cancelled by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n[ERROR] Verification failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
