import asyncio
import websockets

async def test_connection():
    ws = await websockets.connect("wss://echo.websocket.org")
    print(f"Type: {type(ws)}")
    print(f"Dir: {[a for a in dir(ws) if not a.startswith('_')]}")
    print(f"Has 'open': {hasattr(ws, 'open')}")
    print(f"Has 'closed': {hasattr(ws, 'closed')}")
    if hasattr(ws, 'open'):
        print(f"open: {ws.open}")
    if hasattr(ws, 'closed'):
        print(f"closed: {ws.closed}")
    if hasattr(ws, 'state'):
        print(f"state: {ws.state}")
    await ws.close()

asyncio.run(test_connection())
