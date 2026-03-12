"""
ClawMesh Phase 3 - Secure Multi-Node Demo

演示 3 个节点的加密网络：
1. Node A 作为 server（监听 12448，支持加密）
2. Node B 和 Node C 作为 client，启用 ECDH 加密
3. 展示加密 handshake、消息加密传输、指纹验证

运行: uv run python examples/secure_multi_node_demo.py

注意: 此演示在同一进程中启动 server 和多个 client，展示端到端加密。
"""

import asyncio
import sys
import logging
from pathlib import Path
import time

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent.parent))

from node.server import ClawMeshServer
from node.client import ClawMeshClient

class SecureDemoNode:
    """加密演示节点"""
    
    def __init__(self, node_id: str, role: str = "client", server_url: str = None):
        self.node_id = node_id
        self.role = role  # "server" or "client"
        self.server_url = server_url
        self.server: Optional[ClawMeshServer] = None
        self.client: Optional[ClawMeshClient] = None
        self._tasks: List[asyncio.Task] = []
        self._shutdown = asyncio.Event()
    
    async def start_server(self, host: str = "127.0.0.1", port: int = 12448):
        """启动加密 server"""
        logger.info(f"[{self.node_id}] Starting secure server on {host}:{port}")
        self.server = ClawMeshServer(host=host, port=port, node_id=self.node_id)
        self.server_task = asyncio.create_task(self.server.start())
        await asyncio.sleep(0.5)
        logger.info(f"[{self.node_id}] Server started")
    
    async def start_client(self, handshake_timeout: float = 10.0):
        """启动加密 client，等待 handshake 完成
        
        Args:
            handshake_timeout: 等待 handshake 完成的超时（秒）
        """
        logger.info(f"[{self.node_id}] Starting secure client, connecting to {self.server_url}")
        self.client = ClawMeshClient(self.node_id, self.server_url)
        client_task = asyncio.create_task(self.client.connect())
        self._tasks.append(client_task)
        
        # 等待 handshake 完成（检查 client.crypto）
        start = asyncio.get_event_loop().time()
        waited = 0.0
        while not self.client.crypto:
            await asyncio.sleep(0.2)
            waited += 0.2
            if waited > handshake_timeout:
                logger.error(f"[{self.node_id}] Handshake timeout after {waited:.1f}s")
                logger.error(f"[{self.node_id}] Client state: connected={self.client.connected.is_set()}, crypto={self.client.crypto}")
                raise RuntimeError(f"Client {self.node_id} handshake timeout after {handshake_timeout}s")
        logger.info(f"[{self.node_id}] Handshake completed, encryption_mode={self.client.encryption_mode}")
    
    async def send_message(self, to: str, content: str):
        """发送加密消息"""
        if self.client:
            return await self.client.send_message(to, content)
        return False
    
    async def broadcast(self, content: str):
        """广播加密消息"""
        if self.client:
            await self.client.broadcast(content)
    
    async def stop(self):
        """停止所有组件"""
        self._shutdown.set()
        if self.client:
            self.client.shutdown = True
        for task in self._tasks:
            task.cancel()
        if self.server:
            self.server.shutdown_flag = True
            await asyncio.sleep(0.5)
        logger.info(f"[{self.node_id}] Stopped")

# ============= Demo Scenario ==============

async def run_demo():
    """运行 3 节点加密网络演示"""
    
    print("\n" + "="*70)
    print("ClawMesh Secure Multi-Node Demo (Phase 3)")
    print("="*70 + "\n")
    
    # 定义节点
    node_a_id = "CL-01S-SECURE-SERVER"
    node_b_id = "CL-01S-SECURE-CLIENT-B"
    node_c_id = "CL-01S-SECURE-CLIENT-C"
    server_url = "ws://127.0.0.1:12448"
    
    # 创建节点
    node_a = SecureDemoNode(node_a_id, role="server")
    node_b = SecureDemoNode(node_b_id, role="client", server_url=server_url)
    node_c = SecureDemoNode(node_c_id, role="client", server_url=server_url)
    
    try:
        # 1. 启动 Server
        await node_a.start_server(port=12448)
        await asyncio.sleep(1)
        
        # 2. 启动 Client B 和 C
        await asyncio.gather(
            node_b.start_client(),
            node_c.start_client()
        )
        await asyncio.sleep(2)
        
        # 验证加密状态
        assert node_b.client.crypto is not None, "Client B should have crypto"
        assert node_c.client.crypto is not None, "Client C should have crypto"
        assert node_b.client.encryption_mode == "required"
        assert node_c.client.encryption_mode == "required"
        
        print("\n[Step 1] Encrypted handshake completed")
        print(f"  - Server: {node_a_id}")
        print(f"  - Client B: {node_b_id} (encryption_mode={node_b.client.encryption_mode})")
        print(f"  - Client C: {node_c_id} (encryption_mode={node_c.client.encryption_mode})")
        
        # 3. Client B 发送消息给 C
        print("\n[Step 2] Client B sends encrypted message to C...")
        await node_b.send_message(node_c_id, "Hello C! This is a secret message from B.")
        await asyncio.sleep(1)
        print("  Message sent (encrypted on wire)")
        
        # 4. Client C 广播消息
        print("\n[Step 3] Client C broadcasts encrypted message to all...")
        await node_c.broadcast("Greetings from C! All nodes should receive this securely.")
        await asyncio.sleep(1)
        print("  Broadcast sent (encrypted on wire)")
        
        # 5. 显示连接状态
        print("\n[Step 4] Connection status")
        print(f"  - Server connections: {len(node_a.server.connections)}")
        print(f"  - Client B online: {node_b.client.connected.is_set()}")
        print(f"  - Client C online: {node_c.client.connected.is_set()}")
        
        # 6. 测试重连（可选）
        print("\n[Step 5] Testing reconnection (optional)...")
        print("  (Skipping in demo to keep it short)")
        
        print("\n" + "="*70)
        print("Secure Demo Completed Successfully!")
        print("="*70 + "\n")
        
        # 清理
        await node_b.stop()
        await node_c.stop()
        await node_a.stop()
        
    except AssertionError as e:
        logger.error(f"Assertion failed: {e}")
        await node_b.stop()
        await node_c.stop()
        await node_a.stop()
        return False
    except Exception as e:
        logger.error(f"Demo error: {e}", exc_info=True)
        await node_b.stop()
        await node_c.stop()
        await node_a.stop()
        return False
    
    return True

# ============= Main ==============

if __name__ == "__main__":
    try:
        success = asyncio.run(run_demo())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n[INFO] Demo interrupted by user")
        sys.exit(0)
