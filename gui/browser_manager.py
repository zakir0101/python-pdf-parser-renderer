import asyncio
from pathlib import Path

# from playwright.async_api import Browser, Page, Playwright, async_playwright
from playwright.sync_api import Browser, Page, Playwright, sync_playwright


class BrowserManager:
    """Manages a persistent Playwright browser instance for efficient rendering."""

    def __init__(self, viewport_width=800, viewport_height=600):
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.page: Page | None = None
        self.viewport_size = {
            "width": viewport_width,
            "height": viewport_height,
        }

    def start(self):
        """Starts the browser. Call this ONCE when your app initializes."""
        if self.browser:
            print("Browser is already running.")
            return

        print("🚀 Starting browser... (this happens only once)")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=True)
        self.page = self.browser.new_page()
        self.page.set_viewport_size(self.viewport_size)
        print("✅ Browser is running and ready.")

    def render_html(self, input_html_path: str, output_png_path: str):
        """
        The fast rendering function. Call this anytime you need a screenshot.
        """
        if not self.page:
            raise RuntimeError(
                "Browser not started. Call start() before rendering."
            )

        print(f"-> Rendering {input_html_path}...")
        file_uri = Path(input_html_path).resolve().as_uri()

        self.page.goto(file_uri, wait_until="networkidle")
        print("after1")

        print("after2")
        self.page.screenshot(path=output_png_path, full_page=True, type="png")

        print(f"✅ Screenshot saved to {output_png_path}")

    def shutdown(self):
        """Closes the browser. Call this ONCE when your app exits."""
        print(" shutting down browser...")
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        print("✅ Browser shut down.")
