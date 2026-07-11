"""Capture a K Pro authenticated Playwright storage state in a headed browser."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = Path(__file__).resolve().parent / ".secrets" / "kpro_storage_state.json"
BASE_URL = os.getenv("KPRO_BASE_URL", "https://k.owkin.com")


def try_password_login(page, username: str | None, password: str | None) -> None:
    """Fill common password fields when K Pro exposes them; SSO remains manual."""
    if not username or not password:
        return
    try:
        page.locator('input[type="email"], input[name*="user" i], input[name="email"]').first.fill(username, timeout=3_000)
        page.locator('input[type="password"]').first.fill(password, timeout=3_000)
        page.locator('button[type="submit"], input[type="submit"]').first.click(timeout=3_000)
    except PlaywrightTimeoutError:
        pass


def main() -> None:
    load_dotenv(ROOT / ".env")
    base_url = os.getenv("KPRO_BASE_URL", BASE_URL)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    print("Opening K Pro. Complete SSO in the browser if prompted.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(base_url, wait_until="domcontentloaded")
        try_password_login(page, os.getenv("OWKIN_USERNAME"), os.getenv("OWKIN_PASSWORD"))

        # K Pro may keep both its login route and authenticated app under the same
        # origin, so URL polling cannot prove authentication. The person completing
        # SSO explicitly confirms before any cookies/local-storage are saved.
        input("When the K Pro chat app is visible and you are signed in, press Enter here: ")
        context.storage_state(path=str(STATE_PATH))
        print(f"Saved authenticated session state to {STATE_PATH}")
        browser.close()


if __name__ == "__main__":
    main()
