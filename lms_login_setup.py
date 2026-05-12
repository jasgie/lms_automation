"""
lms_login_setup.py
------------------
Run this ONCE to save your Microsoft 365 / ClassEdge login session.

Steps:
  1. A browser window will open and navigate to ClassEdge.
  2. Log in with your Microsoft 365 account (MFA included).
  3. Once your dashboard is visible, the session saves automatically.
  4. Your session is saved to auth.json — no re-login needed daily.

Re-run this whenever the session expires (usually after several days/weeks).
"""

from pathlib import Path
from playwright.sync_api import sync_playwright

AUTH_FILE = Path(__file__).parent / "auth.json"
LMS_URL   = "https://classedge.hccci.edu.ph"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=100)
        context = browser.new_context()
        page    = context.new_page()

        print("=" * 60)
        print("  ClassEdge / Microsoft 365 Login Setup")
        print("=" * 60)
        print(f"\nOpening: {LMS_URL}\n")
        print("Please log in with your Microsoft 365 account.")
        print("Complete MFA if prompted.")
        print("The session will be saved automatically once you reach")
        print("your ClassEdge dashboard.\n")

        page.goto(LMS_URL, wait_until="domcontentloaded", timeout=60_000)

        # Wait until the browser leaves ClassEdge and lands on Microsoft login.
        # This prevents a false-positive: the page briefly sits on classedge.hccci.edu.ph
        # BEFORE the JS redirect to Microsoft fires, which would fool the check below.
        print("Waiting for you to log in...")
        try:
            page.wait_for_function(
                "() => window.location.hostname !== 'classedge.hccci.edu.ph'",
                timeout=10_000,
            )
        except Exception:
            # If no redirect in 10s the site may already have an active session —
            # proceed directly to the post-login check.
            pass

        # Now wait indefinitely for the user to finish MFA and land on the dashboard.
        page.wait_for_function(
            """() => {
                const h = window.location.hostname;
                const p = window.location.pathname.toLowerCase();
                const u = window.location.href.toLowerCase();
                return h === 'classedge.hccci.edu.ph'
                    && !p.includes('/login')
                    && !p.includes('/logout')
                    && !u.includes('microsoftonline')
                    && !u.includes('oauth');
            }""",
            timeout=0,  # wait indefinitely — user may take time with MFA
        )

        # Small delay to let the page fully settle
        page.wait_for_load_state("networkidle", timeout=15_000)

        # Verify once more
        current = page.url
        if "microsoftonline" in current.lower() or "/login" in current.lower():
            print("\nERROR: Login does not appear complete.")
            print("Please try running this again and complete the full login.")
            browser.close()
            return

        context.storage_state(path=str(AUTH_FILE))
        print(f"\nSession saved to: {AUTH_FILE.name}")
        print("You can now run setup_tasks.py to register all scheduled tasks.")
        print("=" * 60)

        browser.close()


if __name__ == "__main__":
    main()

