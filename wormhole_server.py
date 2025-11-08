import asyncio
import websockets
import json
import os
from dotenv import load_dotenv

load_dotenv()

connected_clients = set()
pending_responses = {}

async def handler(websocket):
    first_message  = True
    is_page_client = False
    is_sender      = False
    
    try:
        async for message in websocket:
            if first_message:
                first_message = False
                try:
                    parsed = json.loads(message)
                    if parsed.get("type") == "sender":
                        is_sender  = True
                        code       = parsed.get("code")
                        request_id = parsed.get("request_id")
                        
                        if not connected_clients:
                            await websocket.send(json.dumps({"success": False, "error": "No clients connected"}))
                            return
                        else:
                            message_to_send = json.dumps({"code": code, "request_id": request_id})
                            for client in list(connected_clients):
                                try:
                                    await client.send(message_to_send)
                                    print(f"│   └─ Sent code to page client")
                                except:
                                    connected_clients.discard(client)
                            
                            pending_responses[request_id] = websocket
                        continue
                except:
                    pass
            
            if not is_page_client and not is_sender:
                is_page_client = True
                connected_clients.add(websocket)
                print(f"├─ Page client connected. Total clients: {len(connected_clients)}")
            
            try:
                parsed = json.loads(message)
                request_id = parsed.get("request_id")
                if request_id and request_id in pending_responses:
                    sender_ws = pending_responses.pop(request_id)
                    await sender_ws.send(message)
                else:
                    print(f"│   └─ Response from page: {message}")
            except:
                print(f"│   └─ Response from page: {message}")
                
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if is_page_client:
            connected_clients.discard(websocket)
            print(f"├─ Page client disconnected. Total clients: {len(connected_clients)}")

async def main():
    port = int(os.getenv("wormhole_port", 8765))
    print(f"┌─ ws://localhost:{port}")
    async with websockets.serve(handler, "localhost", port):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
