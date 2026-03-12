"""
Phase 3 Integration Tests - End-to-End Encryption

测试加密 handshake 和消息交换完整流程。

场景：
1. Server 启动（支持加密）
2. Client 连接，发送 handshake（带公钥，要求加密）
3. Server 回复 handshake_ack（带公钥、指纹）
4. 双方计算共享密钥
5. Client 发送加密消息，Server 接收并解密
6. Server 广播加密消息给其他节点
"""

import sys
import asyncio
import json
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import websockets
from adapter.crypto import CryptoManager
from node.server import ClawMeshServer
from node.client import ClawMeshClient

# Helper: run a server in background
async def run_server(port: int = 12449):
    server = ClawMeshServer(host="127.0.0.1", port=port, node_id="TEST-SERVER-001")
    task = asyncio.create_task(server.start())
    await asyncio.sleep(0.5)  # Wait for server to bind
    return server, task

async def test_encrypted_handshake_and_message():
    """Test full encryption flow: handshake + encrypted message"""
    
    port = 12449
    server, server_task = await run_server(port)
    
    try:
        # Create client with encryption required
        client = ClawMeshClient("TEST-CLIENT-001", f"ws://127.0.0.1:{port}")
        
        # Connect in background (will run message loop)
        client_task = asyncio.create_task(client.connect())
        await asyncio.sleep(1)  # Wait for handshake
        
        # Check client is connected and encryption is active
        assert client.crypto is not None, "Client should have crypto manager"
        assert client.encryption_mode == "required", "Encryption mode should be required"
        
        # Send an encrypted text message to server (broadcast)
        sent = await client.send_message("broadcast", "Hello Encrypted World!")
        assert sent is True, "Message should send successfully"
        await asyncio.sleep(0.5)
        
        # Server should receive and decrypt automatically
        # Check server logs or connection count
        assert len(server.connections) == 1, "Server should have 1 connection"
        peer = list(server.connections.values())[0]
        assert peer.encryption_mode == "required", "Server peer encryption mode"
        assert peer.crypto is not None, "Server peer should have crypto"
        
        # Clean close
        client.shutdown = True
        client_task.cancel()
        server.shutdown_flag = True
        await asyncio.sleep(0.5)
        
        print("[OK] Encrypted handshake and message roundtrip")
        return True
        
    finally:
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

async def test_fingerprint_verification():
    """Test fingerprint storage and verification"""
    # This is partially manual; here we test the TrustedFingerprints store
    from adapter.crypto import TrustedFingerprints
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        store_path = Path(tmpdir) / "trusted.json"
        store = TrustedFingerprints(str(store_path))
        
        # Initially empty
        assert store.get("NODE-001") is None
        
        # Set a fingerprint
        store.set("NODE-001", "a1b2c3d4")
        assert store.get("NODE-001") == "a1b2c3d4"
        
        # Verify matches
        assert store.verify("NODE-001", "a1b2c3d4") is True
        assert store.verify("NODE-001", "xxxx") is False
        
        # Persisted to file
        store2 = TrustedFingerprints(str(store_path))
        assert store2.get("NODE-001") == "a1b2c3d4"
        
        print("[OK] TrustedFingerprints store")
        return True

async def test_encrypted_message_routing():
    """Test that server routes encrypted messages between clients"""
    port = 12451
    server, server_task = await run_server(port)
    
    try:
        # Create two clients
        client_a = ClawMeshClient("CLIENT-A", f"ws://127.0.0.1:{port}")
        client_b = ClawMeshClient("CLIENT-B", f"ws://127.0.0.1:{port}")
        
        # Start connections in background (they run indefinitely)
        task_a = asyncio.create_task(client_a.connect())
        task_b = asyncio.create_task(client_b.connect())
        
        # Wait for handshake to complete
        await asyncio.sleep(2)
        
        # Verify both clients have encryption
        assert client_a.crypto is not None, "Client A should have crypto"
        assert client_b.crypto is not None, "Client B should have crypto"
        assert client_a.encryption_mode == "required"
        assert client_b.encryption_mode == "required"
        
        # Client A sends direct message to B via server
        sent = await client_a.send_message("CLIENT-B", "Hello B from A")
        assert sent is True, "A->B message should send"
        await asyncio.sleep(0.5)
        
        # Client B sends broadcast to all (including A)
        await client_b.broadcast("Hello all from B")
        await asyncio.sleep(0.5)
        
        # Server should still have both connections
        assert len(server.connections) == 2, f"Server should have 2 connections, got {len(server.connections)}"
        
        print("[OK] Encrypted message routing (A->B + broadcast)")
        return True
        
    finally:
        # Cleanup
        client_a.shutdown = True
        client_b.shutdown = True
        task_a.cancel()
        task_b.cancel()
        try:
            await asyncio.gather(task_a, task_b, return_exceptions=True)
        except:
            pass
        await asyncio.sleep(0.3)
        server.shutdown_flag = True
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

# ============ Main ============

if __name__ == "__main__":
    print("Running Phase 3 integration tests...\n")
    
    tests = [
        ("Encrypted handshake+message", test_encrypted_handshake_and_message),
        ("Fingerprint store", test_fingerprint_verification),
        ("Encrypted message routing", test_encrypted_message_routing),
    ]
    
    passed = 0
    failed = 0
    
    for name, test in tests:
        try:
            if asyncio.run(test()):
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"[FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print(f"\n[SUMMARY] {passed}/{len(tests)} passed")
    sys.exit(0 if failed == 0 else 1)
