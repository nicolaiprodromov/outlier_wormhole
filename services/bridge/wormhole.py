import asyncio
import os
import subprocess
import time
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

async def inject_wormhole():
    debug_port = os.getenv('chrome_debug_port', '9222')
    user_data_dir = os.getenv('chrome_user_data_dir', '/tmp/chrome-debug')
    
    # Use Playwright's installed chromium
    chromium_path = '/ms-playwright/chromium-1091/chrome-linux/chrome'
    
    chrome_process = subprocess.Popen([
        chromium_path,
        '--headless',
        '--no-sandbox',
        '--disable-dev-shm-usage',
        '--disable-web-security',
        '--allow-running-insecure-content',
        '--reduce-security-for-testing',
        '--ignore-certificate-errors',
        f'--remote-debugging-port={debug_port}',
        '--remote-debugging-address=0.0.0.0',
        f'--user-data-dir={user_data_dir}',
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
            
            if not email or not password:
                print("[Wormhole] Error: OUTLIER_EMAIL and OUTLIER_PASSWORD must be set")
                return
            
            print("[Wormhole] Logging in...")
            
            # Wait for the email input to be visible and enabled
            await page.wait_for_selector('input[type="email"]', state='visible', timeout=10000)
            await page.fill('input[type="email"]', email)
            print(f"[Wormhole] Filled email: {email[:5]}...")
            
            # Wait for password input
            await page.wait_for_selector('input[type="password"]', state='visible', timeout=10000)
            await page.fill('input[type="password"]', password)
            print("[Wormhole] Filled password")
            
            # Take a screenshot before clicking (for debugging)
            await page.screenshot(path='/tmp/before_login.png')
            print("[Wormhole] Screenshot saved to /tmp/before_login.png")
            
            # Look for the login button more carefully
            try:
                # Try different button selectors
                login_button = await page.query_selector('button[type="submit"]')
                if not login_button:
                    login_button = await page.query_selector('button:has-text("Login")')
                if not login_button:
                    login_button = await page.query_selector('button:has-text("Sign in")')
                if not login_button:
                    login_button = await page.query_selector('button:has-text("Log in")')
                
                if login_button:
                    button_text = await login_button.inner_text()
                    print(f"[Wormhole] Found login button with text: '{button_text}'")
                    await login_button.click()
                    await asyncio.sleep(2)  # Give the page time to process the click
                else:
                    print("[Wormhole] Login button not found, trying Enter key...")
                    await page.keyboard.press('Enter')
                    await asyncio.sleep(2)
            except Exception as e:
                print(f"[Wormhole] Error clicking login button: {e}")
            
            print("[Wormhole] Waiting for navigation after login...")
            try:
                # Wait for URL to change away from login page
                for i in range(30):  # 30 seconds timeout
                    await asyncio.sleep(1)
                    current = page.url
                    if 'outlier.ai' in current and '/login' not in current and '/logout' not in current:
                        print(f"[Wormhole] Successfully logged in! Current URL: {current}")
                        break
                    if i == 29:
                        raise Exception("Timeout waiting for login redirect")
                
                # Verify we have cookies
                cookies = await context.cookies()
                csrf_cookie = next((c for c in cookies if c['name'] == '_csrf'), None)
                if csrf_cookie:
                    print(f"[Wormhole] CSRF token found: {csrf_cookie['value'][:20]}...")
                else:
                    print("[Wormhole] WARNING: No CSRF token found!")
                    print(f"[Wormhole] Available cookies: {[c['name'] for c in cookies]}")
            except Exception as e:
                print(f"[Wormhole] Navigation timeout or error: {e}. Current URL: {page.url}")
                print("[Wormhole] Login may have failed - API calls will likely return 401")
                # Still continue to try injection
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
        
        # No need to modify the script - it connects to localhost:8766 (the proxy in this container)
        # The proxy then forwards to wormhole-server:8765 on the Docker network
        
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
