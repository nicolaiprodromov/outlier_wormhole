import asyncio
import os
import subprocess
import time
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

async def inject_wormhole():
    debug_port = os.getenv('chrome_debug_port', '9222')
    
    chrome_process = subprocess.Popen([
        'chrome',
        '--headless',
        f'--remote-debugging-port={debug_port}',
        '--remote-debugging-address=127.0.0.1',
        '--user-data-dir=C:\\temp\\chrome-debug',
        "https://app.outlier.ai/en/expert/login?redirect_url=%2Fexpert&clear=1"
    ])
    
    print("[Wormhole] Launching Chrome...")
    await asyncio.sleep(3)
    
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{debug_port}")
        context = browser.contexts[0]
        page = context.pages[0]
        
        try:
            await page.wait_for_load_state('domcontentloaded', timeout=10000)
        except:
            pass
        
        current_url = page.url
        print(f"[Wormhole] Current page: {current_url}")
        
        if '/login' in current_url:
            email = os.getenv('outlier_email')
            password = os.getenv('outlier_password')
            
            print("[Wormhole] Logging in...")
            await page.fill('input[type="email"]', email)
            await page.fill('input[type="password"]', password)
            await page.click('button:has-text("Login")')
            
            print("[Wormhole] Waiting for dashboard...")
            await page.wait_for_url("**/dashboard", timeout=30000)
        else:
            print("[Wormhole] Already logged in!")
        
        print("[Wormhole] Closing extra tabs...")
        for p in context.pages:
            if 'outlier.ai' not in p.url:
                await p.close()
                print(f"[Wormhole] Closed: {p.url}")
        
        print("[Wormhole] Loading injection script...")
        with open('inject_wormhole.js', 'r') as f:
            script = f.read()
        
        port = os.getenv('wormhole_port', '8765')
        script = script.replace('const PORT = 8765;', f'const PORT = {port};')
        
        async def handle_page(page):
            await page.wait_for_load_state('domcontentloaded')
            if 'outlier.ai' not in page.url:
                print(f"[Wormhole] Skipping non-Outlier page: {page.url}")
                return
            
            already_injected = await page.evaluate("typeof window.__wormhole__ !== 'undefined'")
            if already_injected:
                print(f"[Wormhole] Already injected: {page.url}")
                return
                
            await page.evaluate(script)
            print(f"[Wormhole] Injected into: {page.url}")
            try:
                status = await page.evaluate("window.__wormhole__.status()")
                print(f"[Wormhole] Status: {status}")
            except:
                pass
        
        for p in context.pages:
            if 'outlier.ai' in p.url:
                await handle_page(p)
        
        context.on("page", lambda page: asyncio.create_task(handle_page(page)))
        
        print("[Wormhole] Persistent injection enabled. Monitoring all pages...")
        print("[Wormhole] Press Ctrl+C to stop")
        
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n[Wormhole] Shutting down...")
            chrome_process.terminate()

if __name__ == "__main__":
    asyncio.run(inject_wormhole())
