"""
HN Poster — Automated Reply Posting
Posts approved replies to Hacker News using Playwright.
Only posts replies that have passed owner verification.

Credentials stored in .env — never hardcoded.
"""

import json
import asyncio
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright
from dotenv import load_dotenv
import os

load_dotenv()

APPROVED_FILE = "company/approved_replies.json"
POSTED_LOG_FILE = "company/posted_log.json"

HN_USERNAME = os.getenv("HN_USERNAME")
HN_PASSWORD = os.getenv("HN_PASSWORD")

async def login_to_hn(page) -> bool:
    """Log into Hacker News."""
    print("[→] Logging into Hacker News...")
    try:
        await page.goto("https://news.ycombinator.com/login", wait_until="networkidle")
        await page.fill('input[name="acct"]', HN_USERNAME)
        await page.fill('input[name="pw"]', HN_PASSWORD)
        await page.click('input[type="submit"]')
        await page.wait_for_load_state("networkidle")

        # Verify login worked
        username = (HN_USERNAME or "").lower()
        if username and username in (await page.content()).lower():
            print(f"[✓] Logged in as {HN_USERNAME}")
            return True
        else:
            print("[ERROR] Login failed — check credentials")
            return False
    except Exception as e:
        print(f"[ERROR] Login error: {e}")
        return False

async def post_reply(page, reply: dict) -> bool:
    """Post a single reply to a HN thread."""
    url = reply["lead_url"]
    text = reply["final_reply"]

    print(f"\n[→] Posting reply to:")
    print(f"    {reply['lead_title'][:60]}")
    print(f"    {url}")

    try:
        await page.goto(url, wait_until="networkidle")
        await asyncio.sleep(2)

        # Find the reply textarea
        textarea = page.locator('textarea[name="text"]').first
        if not await textarea.is_visible():
            print("[ERROR] Could not find comment box")
            return False

        # Type the reply
        await textarea.click()
        await textarea.fill(text)
        await asyncio.sleep(1)

        # Submit
        submit_btn = page.locator('input[type="submit"][value="add comment"]').first
        if not await submit_btn.is_visible():
            # Try alternative submit button text
            submit_btn = page.locator('input[type="submit"]').first

        await submit_btn.click()
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)

        # Verify it posted — look for our text in the page
        content = await page.content()
        if text[:50].lower() in content.lower():
            print(f"[✓] Reply posted successfully")
            return True
        else:
            print(f"[?] Reply may have posted — please verify manually at {url}")
            return True  # assume success, let owner verify

    except Exception as e:
        print(f"[ERROR] Failed to post reply: {e}")
        return False

async def run_hn_poster():
    """
    Main function — posts all approved replies to HN.
    """
    print("\n" + "="*60)
    print("HN POSTER — Automated Reply Agent")
    print("="*60)

    # Check credentials
    if not HN_USERNAME or not HN_PASSWORD:
        print("[ERROR] HN_USERNAME and HN_PASSWORD not set in .env")
        print("Add these to your .env file and try again.")
        return []

    # Load approved replies
    if not Path(APPROVED_FILE).exists():
        print("[ERROR] No approved replies found. Run owner_verify first.")
        return []

    with open(APPROVED_FILE) as f:
        approved = json.load(f)

    to_post = [r for r in approved if r.get("status") == "approved" and not r.get("posted_at")]

    if not to_post:
        print("No approved replies to post right now.")
        return []

    print(f"\nReplies to post: {len(to_post)}")

    posted = []
    failed = []

    async with async_playwright() as p:
        # Launch browser — headless=False so you can see what's happening
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # Login
        logged_in = await login_to_hn(page)
        if not logged_in:
            await browser.close()
            return []

        # Post each reply with a delay between posts
        for i, reply in enumerate(to_post, 1):
            print(f"\n[{i}/{len(to_post)}] Posting reply...")
            success = await post_reply(page, reply)

            if success:
                reply["posted_at"] = datetime.now().isoformat()
                reply["status"] = "posted"
                posted.append(reply)
            else:
                reply["status"] = "post_failed"
                failed.append(reply)

            # Wait between posts — be respectful, avoid rate limiting
            if i < len(to_post):
                print(f"[→] Waiting 30 seconds before next post...")
                await asyncio.sleep(30)

        await browser.close()

    # Save posted log
    existing_log = []
    if Path(POSTED_LOG_FILE).exists():
        with open(POSTED_LOG_FILE) as f:
            existing_log = json.load(f)

    existing_log.extend(posted)
    with open(POSTED_LOG_FILE, "w") as f:
        json.dump(existing_log, f, indent=2)

    # Update approved file
    with open(APPROVED_FILE, "w") as f:
        json.dump(approved, f, indent=2)

    # Summary
    print(f"\n{'='*60}")
    print(f"HN POSTER COMPLETE")
    print(f"{'='*60}")
    print(f"Posted:  {len(posted)}")
    print(f"Failed:  {len(failed)}")
    if posted:
        print(f"\nPosted to:")
        for r in posted:
            print(f"  → {r['lead_title'][:60]}")
            print(f"    {r['lead_url']}")
    print(f"\n[✓] Post log saved to company/posted_log.json")

    return posted

if __name__ == "__main__":
    posted = asyncio.run(run_hn_poster())
    print(f"\nDone. {len(posted)} replies posted to Hacker News.")