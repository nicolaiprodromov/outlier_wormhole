import asyncio
import websockets
import json
import sys
import uuid


async def send_command(command, params):
    import os

    wormhole_host = os.getenv("wormhole_server_host", "localhost")
    wormhole_port = os.getenv("wormhole_port", "8765")
    uri = f"ws://{wormhole_host}:{wormhole_port}"
    request_id = str(uuid.uuid4())
    try:
        async with websockets.connect(uri) as websocket:
            message = json.dumps(
                {
                    "type": "sender",
                    "command": command,
                    "params": params,
                    "request_id": request_id,
                }
            )
            await websocket.send(message)
            response = await websocket.recv()
            result = json.loads(response)
            return result
    except Exception as e:
        return {"success": False, "error": str(e)}


async def send_script_async(script_file, input_data=None):
    """
    Legacy function that converts script files to command calls.
    Maps old script-based calls to new command-based architecture.
    """
    try:
        if "create_conversation" in script_file:
            command = "createConversation"
            params = input_data or {}
        elif "send_message" in script_file:
            command = "sendMessage"
            params = input_data or {}
        else:
            return {"success": False, "error": f"Unknown script: {script_file}"}
        print(f"[send.py] Sending command: {command}")
        print(f"[send.py] Params: {json.dumps(params, indent=2)}")
        result = await send_command(command, params)
        return result
    except FileNotFoundError:
        return {"success": False, "error": f"File not found: {script_file}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def send_script_sync(script_file, input_data=None):
    try:
        print(f"[send.py] Processing script: {script_file}")
        print(f"[send.py] Input data: {input_data}")
        result = asyncio.run(send_script_async(script_file, input_data))
        print(f"[send.py] Result: {result}")
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python send.py <script-file.js> [json-input]")
        sys.exit(1)
    script_file = sys.argv[1]
    input_data = None
    if len(sys.argv) > 2:
        try:
            input_data = json.loads(sys.argv[2])
        except json.JSONDecodeError:
            print(f"[Sender] Invalid JSON input: {sys.argv[2]}")
            sys.exit(1)
    result = send_script_sync(script_file, input_data)
    if result.get("success"):
        print(f"[Sender] Result: {result.get('result')}")
    else:
        print(f"[Sender] Error: {result.get('error')}")
