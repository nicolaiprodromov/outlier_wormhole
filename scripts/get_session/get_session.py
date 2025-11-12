import asyncio
import os
import sys
from playwright.async_api import async_playwright
from dotenv import load_dotenv

workspace_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(workspace_root, ".env")
load_dotenv(env_path)


async def get_session(headless=False):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    user_data_dir = os.path.join(script_dir, "chrome_profile")
    chromium_path = os.path.join(
        script_dir, "chrome_standalone/opt/google/chrome/chrome"
    )

    mode = "headless" if headless else "headful"
    print(f"[Get Session] ===== Launching Chrome in {mode} mode =====")
    print(f"[Get Session] Profile directory: {user_data_dir}")

    if headless:
        print("[Get Session] Running headless to convert profile for headless use")
        print("[Get Session] This will sync cookies and session data for headless mode")
    else:
        print("[Get Session] Please log in manually to Outlier")
        print("[Get Session] Press Ctrl+C to stop when done")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir,
            headless=headless,
            executable_path=chromium_path,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        print(f"[Get Session] ✓ Chrome launched in {mode} mode")

        if len(context.pages) > 0:
            page = context.pages[0]
        else:
            page = await context.new_page()

        print("[Get Session] Navigating to https://app.outlier.ai")
        await page.goto(
            "https://app.outlier.ai", wait_until="domcontentloaded", timeout=15000
        )
        await asyncio.sleep(2)

        current_url = page.url
        print(f"[Get Session] Current URL: {current_url}")

        cookies = await context.cookies()
        print(f"[Get Session] Loaded {len(cookies)} cookies")

        if headless:
            if "/dashboard" in current_url:
                print(
                    "[Get Session] ✓✓✓ SUCCESS: Profile converted! Headless mode can access dashboard ✓✓✓"
                )
            elif "/login" in current_url:
                print(
                    "[Get Session] ✗✗✗ FAILURE: Not logged in. Please run in headful mode first (without --headless) ✗✗✗"
                )
            print("[Get Session] Headless conversion complete. Closing in 3 seconds...")
            await asyncio.sleep(3)
            await context.close()
        else:
            print("[Get Session] Session will be saved automatically")
            print("[Get Session] After logging in, press Ctrl+C to stop")

            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                print("\n[Get Session] Shutting down...")
                await context.close()


if __name__ == "__main__":
    headless_mode = "--headless" in sys.argv

    try:
        asyncio.run(get_session(headless=headless_mode))
    except KeyboardInterrupt:
        print("\n[Get Session] Stopped")
