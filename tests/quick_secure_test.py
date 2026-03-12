"""Quick test: server + 2 clients with encryption"""
import asyncio, sys, logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from node.server import ClawMeshServer
from node.client import ClawMeshClient

async def main():
    # Start server
    server = ClawMeshServer(host="127.0.0.1", port=12448, node_id="TEST-SERVER")
    server_task = asyncio.create_task(server.start())
    await asyncio.sleep(0.5)
    print("Server started")

    # Start two clients
    client_a = ClawMeshClient("CLIENT-A", "ws://127.0.0.1:12448")
    client_b = ClawMeshClient("CLIENT-B", "ws://127.0.0.1:12448")
    task_a = asyncio.create_task(client_a.connect())
    task_b = asyncio.create_task(client_b.connect())

    # Wait for handshake
    for i in range(50):
        if client_a.crypto and client_b.crypto:
            print(f"Both clients handshake done! A mode={client_a.encryption_mode}, B mode={client_b.encryption_mode}")
            break
        await asyncio.sleep(0.2)
    else:
        print("TIMEOUT: handshake not completed")
        print(f"A crypto: {client_a.crypto}, B crypto: {client_b.crypto}")

    # Send message A->B
    if client_a.crypto:
        await client_a.send_message("CLIENT-B", "Hello B from A")
        print("Message sent")

    # Cleanup
    client_a.shutdown = True
    client_b.shutdown = True
    server.shutdown_flag = True
    await asyncio.sleep(0.5)
    server_task.cancel()
    task_a.cancel()
    task_b.cancel()
    try:
        await asyncio.gather(server_task, task_a, task_b, return_exceptions=True)
    except:
        pass
    print("Test complete")

asyncio.run(main())
