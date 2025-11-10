import asyncio
import os
from datetime import datetime
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()


async def inject_wormhole():
    proxy_port = os.getenv("proxy_port", "8766")

    # Use standalone Chrome with pre-authenticated profile
    chrome_path = "/app/chrome_standalone/opt/google/chrome/chrome"
    user_data_dir = "/app/chrome_profile"

    print("[Wormhole] ===== Chrome Configuration =====")
    print(f"[Wormhole] Chrome executable: {chrome_path}")
    print(f"[Wormhole] User data directory: {user_data_dir}")
    print(f"[Wormhole] Proxy port: {proxy_port}")

    # Verify profile exists
    if not os.path.exists(user_data_dir):
        print(f"[Wormhole] ERROR: Profile directory not found: {user_data_dir}")
        return

    print(f"[Wormhole] ✓ Profile directory exists")

    # Check for important profile files
    profile_files = ["Default/Cookies", "Default/Preferences", "Local State"]
    for pfile in profile_files:
        full_path = os.path.join(user_data_dir, pfile)
        if os.path.exists(full_path):
            size = os.path.getsize(full_path)
            print(f"[Wormhole] ✓ Found {pfile} ({size} bytes)")
        else:
            print(f"[Wormhole] ⚠ Missing {pfile}")

    print("[Wormhole] ===== Starting Chrome with Persistent Context =====")

    async with async_playwright() as p:
        # Use launch_persistent_context to properly load the user profile
        context = await p.chromium.launch_persistent_context(
            user_data_dir,
            headless=True,
            executable_path=chrome_path,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--allow-running-insecure-content",
                "--reduce-security-for-testing",
                "--ignore-certificate-errors",
                "--disable-gpu",
                "--disable-software-rasterizer",
            ],
        )

        print("[Wormhole] ✓ Chrome launched with persistent context")

        # Get the default page or create a new one
        if len(context.pages) > 0:
            page = context.pages[0]
        else:
            page = await context.new_page()

        def handle_console(msg):
            if msg.type in ["error", "warning"]:
                print(f"[Console {msg.type.upper()}] {msg.text}")

        page.on("console", handle_console)

        # Log cookies to verify session
        cookies = await context.cookies()
        print(f"[Wormhole] Loaded {len(cookies)} cookies from profile")
        csrf_cookie = next((c for c in cookies if c["name"] == "_csrf"), None)
        if csrf_cookie:
            print(f"[Wormhole] ✓ CSRF token found: {csrf_cookie['value'][:20]}...")
        else:
            print("[Wormhole] ⚠ No CSRF token in cookies yet")

        print("[Wormhole] ===== Navigating to Outlier =====")
        print("[Wormhole] Navigating to https://app.outlier.ai")

        try:
            await page.goto(
                "https://app.outlier.ai", wait_until="domcontentloaded", timeout=15000
            )
            await asyncio.sleep(2)
        except Exception as e:
            print(f"[Wormhole] Navigation error: {e}")

        current_url = page.url
        print(f"[Wormhole] Current URL: {current_url}")

        # Take screenshot to verify state
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = f"/app/data/auth_check_{timestamp}.png"
        await page.screenshot(path=screenshot_path)
        print(f"[Wormhole] Screenshot saved: {screenshot_path}")

        # Check authentication status
        if "/dashboard" in current_url:
            print(
                "[Wormhole] ✓✓✓ SUCCESS: Redirected to /dashboard - USER IS LOGGED IN ✓✓✓"
            )
        elif "/login" in current_url:
            print(
                "[Wormhole] ✗✗✗ FAILURE: Redirected to /login - USER IS NOT LOGGED IN ✗✗✗"
            )
            print(
                "[Wormhole] ERROR: Session expired or invalid. Please run get_session.py to re-authenticate."
            )
            await context.close()
            return
        else:
            print(f"[Wormhole] ⚠ Unexpected URL: {current_url}")
            print("[Wormhole] Waiting a bit more to see if redirect happens...")
            await asyncio.sleep(3)
            current_url = page.url
            print(f"[Wormhole] URL after wait: {current_url}")

            if "/dashboard" not in current_url:
                print("[Wormhole] ERROR: Not on dashboard. Cannot proceed.")
                await context.close()
                return

        print("[Wormhole] ===== Session Verified - Proceeding with Injection =====")

        print("[Wormhole] Closing extra tabs...")
        for p in context.pages:
            if "outlier.ai" not in p.url:
                await p.close()
                print(f"[Wormhole] Closed: {p.url}")

        print("[Wormhole] Loading injection script...")
        with open("inject_wormhole.js", "r") as f:
            script_template = f.read()

        script = script_template.replace(
            "const PORT = 8766;", f"const PORT = {proxy_port};"
        )

        async def handle_page(page):
            page.on("console", handle_console)

            await page.wait_for_load_state("domcontentloaded")
            if "outlier.ai" not in page.url:
                print(f"[Wormhole] Skipping non-Outlier page: {page.url}")
                return

            already_injected = await page.evaluate(
                "typeof window.__wormhole__ !== 'undefined'"
            )
            if already_injected:
                print(f"[Wormhole] Already injected: {page.url}")
                return

            await page.evaluate(script)
            print(f"[Wormhole] ✓ Injected into: {page.url}")
            try:
                status = await page.evaluate("window.__wormhole__.status()")
                print(f"[Wormhole] Status: {status}")
            except:
                pass

        for p in context.pages:
            if "outlier.ai" in p.url:
                await handle_page(p)

        context.on("page", lambda page: asyncio.create_task(handle_page(page)))

        print("[Wormhole] ===== Wormhole Active =====")
        print("[Wormhole] Persistent injection enabled. Monitoring all pages...")
        print("[Wormhole] Press Ctrl+C to stop")

        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n[Wormhole] Shutting down...")
            await context.close()


if __name__ == "__main__":
    asyncio.run(inject_wormhole())
