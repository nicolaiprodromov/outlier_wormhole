import asyncio
import websockets
import os


async def proxy_handler(client_websocket):
    server_host = os.getenv("wormhole_server_host", "wormhole-server")
    server_port = int(os.getenv("wormhole_port", 8765))
    server_uri = f"ws://{server_host}:{server_port}"

    try:
        async with websockets.connect(server_uri) as server_websocket:
            print(f"[Proxy] Connected browser client to {server_uri}")

            async def client_to_server():
                try:
                    async for message in client_websocket:
                        await server_websocket.send(message)
                except websockets.exceptions.ConnectionClosed:
                    pass

            async def server_to_client():
                try:
                    async for message in server_websocket:
                        await client_websocket.send(message)
                except websockets.exceptions.ConnectionClosed:
                    pass

            await asyncio.gather(
                client_to_server(), server_to_client(), return_exceptions=True
            )
    except Exception as e:
        print(f"[Proxy] Error: {e}")
    finally:
        print("[Proxy] Connection closed")


async def main():
    proxy_port = int(os.getenv("proxy_port", 8766))
    print(f"[Proxy] Starting WebSocket proxy on 0.0.0.0:{proxy_port}")
    print(
        f"[Proxy] Forwarding to {os.getenv('wormhole_server_host', 'wormhole-server')}:{os.getenv('wormhole_port', 8765)}"
    )

    async with websockets.serve(proxy_handler, "0.0.0.0", proxy_port):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
