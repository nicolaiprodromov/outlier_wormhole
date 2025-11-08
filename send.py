# :)
# :)

import asyncio
import websockets
import json
import sys
import uuid

async def send_script(script_content, input_data=None):
    uri = "ws://localhost:8765"
    request_id = str(uuid.uuid4())
    
    if input_data:
        script_content = script_content.replace('INPUT_DATA', json.dumps(input_data))
    
    try:
        async with websockets.connect(uri) as websocket:
            message = json.dumps({
                "type": "sender",
                "code": script_content,
                "request_id": request_id
            })
            await websocket.send(message)
            
            response = await websocket.recv()
            result = json.loads(response)
            
            return result
                
    except Exception as e:
        return {"success": False, "error": str(e)}

async def send_script_async(script_file, input_data=None):
    try:
        with open(script_file, 'r') as f:
            script_content = f.read()
        
        print(f"[send.py] Sending script: {script_file}")
        
        result = await send_script(script_content, input_data)
        
        return result
        
    except FileNotFoundError:
        return {"success": False, "error": f"File not found: {script_file}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def send_script_sync(script_file, input_data=None):
    try:
        with open(script_file, 'r') as f:
            script_content = f.read()
        
        print(f"[send.py] Sending script: {script_file}")
        print(f"[send.py] Input data: {input_data}")
        
        result = asyncio.run(send_script(script_content, input_data))
        
        print(f"[send.py] Result: {result}")
        return result
        
    except FileNotFoundError:
        return {"success": False, "error": f"File not found: {script_file}"}
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
