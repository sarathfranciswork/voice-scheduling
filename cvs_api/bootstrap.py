"""
Playwright-based session bootstrapper for CVS APIs.

Contains two bootstrappers:
  1. PlaywrightBootstrapper -- guest session (headless, extracts guest token + Akamai cookies)
  2. AuthenticatedBootstrapper -- CVS login with MFA (non-headless, extracts authenticated cookies)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from cvs_api.config import CVS_LOGIN_URL

logger = logging.getLogger(__name__)

TOKEN_URL_FRAGMENT = "/api/guest/v1/token"
INTROSPECT_URL_FRAGMENT = "/api/retail/token/v1/introspect"

CVS_ENTRY_URL = "https://www.cvs.com/immunizations/covid-19-vaccine"
CVS_SCHEDULING_URL = "https://www.cvs.com/scheduling/patient-lookup?lob=rximz&flow=vaccine"

PERSISTENT_PROFILE_DIR = str(
    Path(__file__).resolve().parent.parent / ".cvs_auth_browser"
)

# Anti-detection Chromium args
_STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-infobars",
    "--disable-background-timer-throttling",
    "--disable-popup-blocking",
]

# JS injected before every page load to mask automation signals
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});
window.chrome = { runtime: {} };
"""


class BootstrapResult:
    """Holds the extracted session data from a Playwright bootstrap."""

    def __init__(
        self,
        token: str,
        token_expires_at: float,
        cookies: dict[str, str],
        headers: dict[str, str],
    ):
        self.token = token
        self.token_expires_at = token_expires_at
        self.cookies = cookies
        self.headers = headers


class PlaywrightBootstrapper:
    """Bootstraps a real CVS browser session to extract cookies and guest token."""

    def __init__(self):
        self._last_result: BootstrapResult | None = None

    @property
    def has_valid_session(self) -> bool:
        if self._last_result is None:
            return False
        return time.time() < self._last_result.token_expires_at

    async def bootstrap(self) -> BootstrapResult:
        """Launch headless browser, navigate to CVS, intercept the token, extract cookies."""
        logger.info("Starting Playwright bootstrap for CVS session...")

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            )

        token_data: dict[str, Any] = {}
        token_captured = asyncio.Event()
        captured_request_headers: dict[str, str] = {}

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:147.0) "
                    "Gecko/20100101 Firefox/147.0"
                ),
                viewport={"width": 1280, "height": 720},
                locale="en-US",
            )

            page = await context.new_page()

            async def handle_response(response):
                nonlocal token_data, captured_request_headers
                if token_captured.is_set():
                    return
                if TOKEN_URL_FRAGMENT in response.url and response.status == 200:
                    try:
                        body = await response.json()
                        if "access_token" in body:
                            token_data = body
                            captured_request_headers = dict(response.request.headers)
                            token_captured.set()
                            logger.info("Intercepted guest token from browser network")
                    except Exception:
                        pass

            page.on("response", handle_response)

            # Navigate to CVS page and wait for page load + Akamai JS
            logger.info(f"Navigating to {CVS_ENTRY_URL}")
            try:
                await page.goto(CVS_ENTRY_URL, wait_until="load", timeout=30_000)
            except Exception as e:
                logger.warning(f"Navigation issue (continuing): {e}")

            # Wait up to 15 seconds for the token to be captured from page JS
            try:
                await asyncio.wait_for(token_captured.wait(), timeout=15)
            except asyncio.TimeoutError:
                pass

            # Check cookies for the token
            if not token_captured.is_set():
                tok = await self._extract_token_from_cookies(context)
                if tok:
                    token_data = tok
                    token_captured.set()

            # If not yet captured, wait for Akamai to set _abck, then use injected fetch
            if not token_captured.is_set():
                logger.info("Waiting for Akamai cookies before injected fetch...")
                akamai_ready = await self._wait_for_akamai_cookies(context, timeout=15)
                if akamai_ready:
                    for attempt in range(3):
                        logger.info(f"Injected fetch attempt {attempt + 1}...")
                        js_result = await self._injected_token_fetch(page)
                        if js_result and js_result.get("access_token"):
                            # Capture visitor/experience IDs from injected fetch
                            if js_result.get("_visitorId"):
                                captured_request_headers["x-visitor-id"] = js_result.pop("_visitorId")
                            if js_result.get("_experienceId"):
                                captured_request_headers["x-experienceid"] = js_result.pop("_experienceId")
                            token_data = js_result
                            token_captured.set()
                            logger.info("Acquired token via injected fetch")
                            break
                        elif js_result and js_result.get("error") == 403:
                            logger.info("Akamai still challenging, waiting 3s before retry...")
                            await page.wait_for_timeout(3000)
                        else:
                            logger.warning(f"Injected fetch result: {js_result}")
                            await page.wait_for_timeout(2000)

            # Strategy: Navigate to scheduling page as last resort
            if not token_captured.is_set():
                logger.info(f"Trying scheduling page: {CVS_SCHEDULING_URL}")
                try:
                    await page.goto(CVS_SCHEDULING_URL, wait_until="load", timeout=20_000)
                    await asyncio.wait_for(token_captured.wait(), timeout=10)
                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    logger.warning(f"Scheduling page issue: {e}")

                if not token_captured.is_set():
                    tok = await self._extract_token_from_cookies(context)
                    if tok:
                        token_data = tok
                        token_captured.set()

            if not token_captured.is_set():
                await browser.close()
                raise RuntimeError(
                    "Could not acquire CVS guest token after all strategies. "
                    "Set CVS_GUEST_TOKEN env var as fallback."
                )

            # Extract all cookies
            browser_cookies = await context.cookies()
            cookies: dict[str, str] = {}
            for c in browser_cookies:
                if "cvs.com" in c.get("domain", ""):
                    cookies[c["name"]] = c["value"]

            logger.info(f"Extracted {len(cookies)} CVS cookies from browser")
            await browser.close()

        access_token = token_data["access_token"]
        expires_in = int(token_data.get("expires_in", 899))
        token_expires_at = time.time() + expires_in - 60

        useful_headers: dict[str, str] = {}
        for key in ("x-visitor-id", "x-experienceid", "x-adobe-ecid", "x-api-key"):
            if key in captured_request_headers:
                useful_headers[key] = captured_request_headers[key]

        result = BootstrapResult(
            token=access_token,
            token_expires_at=token_expires_at,
            cookies=cookies,
            headers=useful_headers,
        )
        self._last_result = result

        logger.info(
            f"Bootstrap complete: token expires in {expires_in}s, "
            f"{len(cookies)} cookies captured"
        )
        return result

    async def _wait_for_akamai_cookies(self, context, timeout: int = 15) -> bool:
        """Poll cookies until _abck is set (indicates Akamai challenge completed)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            cookies = await context.cookies()
            cookie_names = {c["name"] for c in cookies}
            if "_abck" in cookie_names:
                logger.info("Akamai cookies detected (_abck present)")
                return True
            await asyncio.sleep(1)
        logger.warning("Akamai cookies not detected within timeout")
        return False

    async def _injected_token_fetch(self, page) -> dict[str, Any] | None:
        """Use the page's fetch API to make the token call with the browser's cookies.

        Mirrors the real CVS token request: uses CONTENT_API_KEY plus the
        additional headers that the scheduling UI sends.
        """
        try:
            return await page.evaluate("""
                async () => {
                    try {
                        const visitorId = crypto.randomUUID();
                        const clientRefId = crypto.randomUUID();
                        const expId = crypto.randomUUID();
                        const resp = await fetch('/api/guest/v1/token', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'Accept': 'application/json, text/plain, */*',
                                'x-api-key': '5fmbGDY003CAfvb3nPPxI9qyjuGfugG2',
                                'x-channel': 'WEB',
                                'x-visitor-id': visitorId,
                                'x-experienceid': expId,
                                'x-clientrefid': clientRefId,
                                'access-control-expose-headers': 'grid',
                                'cat': 'NGS_IMZ',
                                'category': 'NGS_IMZ',
                                'x-cat': 'NGS_WEB',
                                'ADRUM': 'isAjax:true',
                            },
                            body: JSON.stringify({})
                        });
                        if (resp.ok) {
                            const data = await resp.json();
                            data._visitorId = visitorId;
                            data._experienceId = expId;
                            return data;
                        }
                        return {error: resp.status};
                    } catch(e) {
                        return {error: e.message};
                    }
                }
            """)
        except Exception as e:
            logger.warning(f"Injected fetch exception: {e}")
            return None

    async def _extract_token_from_cookies(self, context) -> dict[str, Any] | None:
        """Check if the browser cookies contain an access_token."""
        cookies = await context.cookies()
        for c in cookies:
            if c.get("name") == "access_token" and c.get("value"):
                logger.info("Found access_token in browser cookies")
                return {
                    "access_token": c["value"],
                    "expires_in": "899",
                }
        return None

    async def refresh_if_needed(self) -> BootstrapResult | None:
        """Re-bootstrap if the current session is expired or about to expire."""
        if self.has_valid_session:
            return self._last_result
        logger.info("Session expired or missing, re-bootstrapping...")
        return await self.bootstrap()


class AuthenticatedBootstrapper:
    """Drives CVS login via Playwright to obtain authenticated session cookies.

    Supports three login modes:
      A. OTP (passwordless): email → send SMS code → enter OTP → verify DOB
      B. Password: email → click "Enter password" → fill password → authenticated
      C. Manual (redirect): open CVS login page, user completes login manually

    The browser context persists between calls so the session stays open.
    """

    def __init__(self, headless: bool = False):
        self._headless = headless
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._manual_login_active: bool = False

    async def _is_alive(self) -> bool:
        """Check whether the current page/context is still usable."""
        if self._page is None:
            return False
        try:
            await self._page.evaluate("1")
            return True
        except Exception:
            return False

    async def _ensure_browser(self) -> None:
        """Launch an ephemeral (non-persistent) browser for automated flows."""
        if self._context is not None:
            if await self._is_alive():
                return
            logger.info("Browser is no longer alive, relaunching...")
            await self._force_close()

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            )
        self._playwright = await async_playwright().__aenter__()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:147.0) "
                "Gecko/20100101 Firefox/147.0"
            ),
            viewport={"width": 1280, "height": 720},
            locale="en-US",
        )
        self._page = await self._context.new_page()

    async def _ensure_persistent_browser(self) -> None:
        """Launch a persistent-profile browser with stealth patches for manual login.

        Uses launch_persistent_context so the browser profile (cookies, localStorage,
        Akamai sensor data) survives across sessions, making it look like a real user.
        Anti-detection JS is injected to mask Playwright automation signals.
        """
        if self._context is not None:
            if await self._is_alive():
                return
            logger.info("Persistent browser is no longer alive, relaunching...")
            await self._force_close()

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            )

        os.makedirs(PERSISTENT_PROFILE_DIR, exist_ok=True)

        self._playwright = await async_playwright().__aenter__()
        # launch_persistent_context returns a BrowserContext directly (no Browser)
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=PERSISTENT_PROFILE_DIR,
            headless=False,
            args=_STEALTH_ARGS,
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
            locale="en-US",
            ignore_default_args=["--enable-automation"],
        )
        # Inject stealth patches before any page navigation
        await self._context.add_init_script(_STEALTH_JS)

        self._browser = None  # persistent context has no separate Browser
        self._page = (
            self._context.pages[0]
            if self._context.pages
            else await self._context.new_page()
        )
        logger.info("Persistent browser launched with stealth patches (profile: %s)", PERSISTENT_PROFILE_DIR)

    async def _force_close(self) -> None:
        """Forcibly clear all browser references (for recovery after a dead browser)."""
        # Persistent context: close context directly
        # Ephemeral: close browser (which also closes its contexts)
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        elif self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        try:
            if self._playwright:
                await self._playwright.__aexit__(None, None, None)
        except Exception:
            pass
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None

    async def _detect_page_error(self) -> str | None:
        """Check for visible error messages on the current page."""
        page = self._page
        if page is None:
            return None
        try:
            error_el = page.locator('[class*="error"], [class*="alert"], [role="alert"]').first
            error_text = await error_el.text_content(timeout=2000)
            if error_text and error_text.strip():
                return error_text.strip()
        except Exception:
            pass
        return None

    async def start_login(self, email: str) -> dict[str, Any]:
        """Step 1: Navigate to CVS login, enter email, select SMS MFA, send code.

        Returns:
            {"status": "code_sent", "mfa_method": "sms"} -- OTP was sent
            {"status": "authenticated", "cookies": {...}} -- auto-login (KMSI cookies)
            {"status": "error", "message": "..."} -- failure
        """
        await self._ensure_browser()
        page = self._page
        assert page is not None

        logger.info("Navigating to CVS login page: %s", CVS_LOGIN_URL)
        try:
            await page.goto(CVS_LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
        except Exception as e:
            logger.warning("Login page navigation issue: %s", e)

        await page.wait_for_timeout(2000)

        # --- Look-up page: enter email and click Continue ---
        try:
            email_input = page.locator(
                'input[id="emailField"], '
                'input[name="emailField"], '
                'input[aria-label*="Mobile number or email"], '
                'input[aria-label*="email"], '
                'input[placeholder*="email"]'
            ).first
            await email_input.wait_for(state="visible", timeout=10_000)
            await email_input.fill(email)
            logger.info("Filled email field on look-up page")

            continue_btn = page.locator(
                'button:has-text("Continue"), '
                'button[type="submit"]'
            ).first
            await continue_btn.wait_for(state="visible", timeout=5_000)
            await continue_btn.click()
            logger.info("Clicked Continue")

        except Exception as e:
            logger.error("Failed to fill look-up page: %s", e)
            return {"status": "error", "message": f"Could not fill email on look-up page: {e}"}

        # Wait for navigation to MFA channel selection page
        await page.wait_for_timeout(3000)

        current_url = page.url
        logger.info("Post-email URL: %s", current_url)

        # Check if already authenticated (KMSI cookies)
        if "one-time-passcode" not in current_url and "verify" not in current_url:
            cookies = await self.get_cookies()
            if cookies:
                introspect_ok = await self._check_introspect(cookies)
                if introspect_ok:
                    logger.info("Auto-login succeeded via KMSI cookies")
                    return {"status": "authenticated", "cookies": cookies}

        # Check for error messages
        err = await self._detect_page_error()
        if err:
            logger.warning("Error on look-up page: %s", err)
            return {"status": "error", "message": err}

        # --- MFA channel selection page: select Text (SMS) and click Send code ---
        try:
            # Wait for the MFA channel page to load
            await page.wait_for_url("**/one-time-passcode**", timeout=10_000)
            await page.wait_for_timeout(1000)

            # Select the Text/SMS radio button (usually first and pre-selected)
            text_radio = page.locator(
                'input[type="radio"][value*="sms"], '
                'input[type="radio"]:first-of-type'
            ).first
            try:
                await text_radio.wait_for(state="attached", timeout=3_000)
                if not await text_radio.is_checked():
                    await text_radio.check()
                    logger.info("Selected SMS radio button")
            except Exception:
                logger.info("SMS radio may already be selected or not visible (proceeding)")

            send_code_btn = page.locator(
                'button:has-text("Send code"), '
                'button[type="submit"]'
            ).first
            await send_code_btn.wait_for(state="visible", timeout=5_000)
            await send_code_btn.click()
            logger.info("Clicked 'Send code'")

        except Exception as e:
            logger.error("Failed on MFA channel selection: %s", e)
            return {"status": "error", "message": f"Could not send verification code: {e}"}

        await page.wait_for_timeout(2000)
        logger.info("Verification code sent via SMS")
        return {"status": "code_sent", "mfa_method": "sms"}

    async def submit_otp(self, code: str) -> dict[str, Any]:
        """Step 2: Enter the 6-digit OTP code and confirm.

        Returns:
            {"status": "dob_required"} -- DOB verification page loaded
            {"status": "authenticated", "cookies": {...}} -- auth complete (no DOB needed)
            {"status": "error", "message": "..."} -- failure
        """
        if self._page is None:
            return {"status": "error", "message": "No active login session. Call start_login first."}

        page = self._page
        logger.info("Submitting OTP code...")

        try:
            code_input = page.locator(
                'input[inputmode="numeric"], '
                'input[aria-label*="code"], '
                'input[aria-label*="digit"], '
                'input[id*="otp"], '
                'input[id*="code"], '
                'input[type="tel"]'
            ).first
            await code_input.wait_for(state="visible", timeout=10_000)
            await code_input.fill(code)
            logger.info("Filled OTP code field")

            confirm_btn = page.locator(
                'button:has-text("Confirm code"), '
                'button:has-text("Confirm"), '
                'button[type="submit"]'
            ).first
            await confirm_btn.wait_for(state="visible", timeout=5_000)
            await confirm_btn.click()
            logger.info("Clicked 'Confirm code'")

        except Exception as e:
            logger.error("Failed to submit OTP: %s", e)
            return {"status": "error", "message": f"Could not submit OTP code: {e}"}

        # Wait for navigation after OTP confirmation
        await page.wait_for_timeout(4000)

        current_url = page.url
        logger.info("Post-OTP URL: %s", current_url)

        # Check for OTP errors (wrong code, expired)
        if "one-time-passcode" in current_url:
            err = await self._detect_page_error()
            if err:
                return {"status": "error", "message": err}
            return {"status": "error", "message": "OTP verification failed. Code may be incorrect or expired."}

        # Check if DOB verification page loaded
        if "verify-user" in current_url:
            logger.info("DOB verification page detected")
            return {"status": "dob_required"}

        # Rare: directly authenticated without DOB step
        cookies = await self.get_cookies()
        if cookies:
            introspect_ok = await self._check_introspect(cookies)
            if introspect_ok:
                logger.info("Authenticated after OTP without DOB step")
                return {"status": "authenticated", "cookies": cookies}

        return {"status": "dob_required"}

    async def verify_dob(self, month: str, day: str, year: str) -> dict[str, Any]:
        """Step 3: Enter date of birth and complete authentication.

        Args:
            month: Two-digit month (e.g. "10")
            day: Two-digit day (e.g. "15")
            year: Four-digit year (e.g. "1990")

        Returns:
            {"status": "authenticated", "cookies": {...}} -- success
            {"status": "error", "message": "..."} -- failure
        """
        if self._page is None:
            return {"status": "error", "message": "No active login session."}

        page = self._page
        logger.info("Entering date of birth for verification...")

        try:
            month_input = page.locator(
                'input[aria-label*="Month"], '
                'input[id*="month"], '
                'input[name*="month"], '
                'input[placeholder*="MM"]'
            ).first
            await month_input.wait_for(state="visible", timeout=10_000)
            await month_input.fill(month)

            day_input = page.locator(
                'input[aria-label*="Day"], '
                'input[id*="day"], '
                'input[name*="day"], '
                'input[placeholder*="DD"]'
            ).first
            await day_input.wait_for(state="visible", timeout=5_000)
            await day_input.fill(day)

            year_input = page.locator(
                'input[aria-label*="Year"], '
                'input[id*="year"], '
                'input[name*="year"], '
                'input[placeholder*="YYYY"]'
            ).first
            await year_input.wait_for(state="visible", timeout=5_000)
            await year_input.fill(year)

            logger.info("Filled DOB fields: %s/%s/%s", month, day, year)

            verify_btn = page.locator(
                'button:has-text("Verify date of birth"), '
                'button:has-text("Verify"), '
                'button[type="submit"]'
            ).first
            await verify_btn.wait_for(state="visible", timeout=5_000)
            await verify_btn.click()
            logger.info("Clicked 'Verify date of birth'")

        except Exception as e:
            logger.error("Failed to submit DOB: %s", e)
            return {"status": "error", "message": f"Could not submit date of birth: {e}"}

        # Wait for processing (the spinner page can take several seconds)
        await page.wait_for_timeout(8000)

        current_url = page.url
        logger.info("Post-DOB URL: %s", current_url)

        # Check for DOB errors
        if "verify-user" in current_url:
            err = await self._detect_page_error()
            if err:
                return {"status": "error", "message": err}
            # May still be processing -- wait longer
            await page.wait_for_timeout(5000)

        cookies = await self.get_cookies()
        if not cookies:
            return {"status": "error", "message": "No cookies obtained after DOB verification"}

        introspect_ok = await self._check_introspect(cookies)
        if introspect_ok:
            logger.info("Authentication succeeded after DOB verification")
            return {"status": "authenticated", "cookies": cookies}

        # Cookies present but introspect didn't confirm -- may still work
        logger.warning("Cookies obtained but introspect did not confirm authentication")
        return {"status": "authenticated", "cookies": cookies}

    async def start_login_with_password(self, email: str, password: str) -> dict[str, Any]:
        """Login using email + password (no OTP/DOB needed).

        Navigates to look-up page, enters email, clicks "Enter password" link,
        fills password, clicks Continue. Returns authenticated or error.
        """
        await self._ensure_browser()
        page = self._page
        assert page is not None

        logger.info("Navigating to CVS login page for password flow: %s", CVS_LOGIN_URL)
        try:
            await page.goto(CVS_LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
        except Exception as e:
            logger.warning("Login page navigation issue: %s", e)

        await page.wait_for_timeout(2000)

        # --- Look-up page: enter email and click Continue ---
        try:
            email_input = page.locator(
                'input[id="emailField"], '
                'input[name="emailField"], '
                'input[aria-label*="Mobile number or email"], '
                'input[aria-label*="email"], '
                'input[placeholder*="email"]'
            ).first
            await email_input.wait_for(state="visible", timeout=10_000)
            await email_input.fill(email)
            logger.info("Filled email field on look-up page")

            continue_btn = page.locator(
                'button:has-text("Continue"), '
                'button[type="submit"]'
            ).first
            await continue_btn.wait_for(state="visible", timeout=5_000)
            await continue_btn.click()
            logger.info("Clicked Continue")
        except Exception as e:
            return {"status": "error", "message": f"Could not fill email: {e}"}

        await page.wait_for_timeout(3000)

        # --- On MFA page, click "Enter password" link ---
        try:
            enter_pw_link = page.locator(
                'a:has-text("Enter password"), '
                'button:has-text("Enter password")'
            ).first
            await enter_pw_link.wait_for(state="visible", timeout=8_000)
            await enter_pw_link.click()
            logger.info("Clicked 'Enter password' link")
        except Exception as e:
            return {"status": "error", "message": f"Could not find 'Enter password' option: {e}"}

        await page.wait_for_timeout(2000)

        # --- Password page: fill password and click Continue ---
        try:
            pw_input = page.locator(
                'input[type="password"], '
                'input[id*="password"], '
                'input[name*="password"]'
            ).first
            await pw_input.wait_for(state="visible", timeout=10_000)
            await pw_input.fill(password)
            logger.info("Filled password field")

            continue_btn = page.locator(
                'button:has-text("Continue"), '
                'button[type="submit"]'
            ).first
            await continue_btn.wait_for(state="visible", timeout=5_000)
            await continue_btn.click()
            logger.info("Clicked Continue on password page")
        except Exception as e:
            return {"status": "error", "message": f"Could not submit password: {e}"}

        # Wait for auth to complete (password flow is direct, no DOB)
        await page.wait_for_timeout(5000)

        current_url = page.url
        logger.info("Post-password URL: %s", current_url)

        # Check for errors on password page
        if "password" in current_url:
            err = await self._detect_page_error()
            if err:
                return {"status": "error", "message": err}
            return {"status": "error", "message": "Password login failed. Check credentials."}

        cookies = await self.get_cookies()
        if not cookies:
            return {"status": "error", "message": "No cookies obtained after password login"}

        introspect_ok = await self._check_introspect(cookies)
        if introspect_ok:
            logger.info("Password login succeeded")
            return {"status": "authenticated", "cookies": cookies}

        logger.warning("Cookies obtained but introspect did not confirm")
        return {"status": "authenticated", "cookies": cookies}

    async def open_for_manual_login(self) -> dict[str, Any]:
        """Open CVS login page in a stealth persistent browser for manual login.

        Uses a persistent profile with anti-detection patches so Akamai
        does not flag the browser as a bot. The user completes login manually.
        Call poll_auth_status() periodically to detect when login completes.
        """
        # Close any stale browser, then launch persistent (stealth) browser
        await self.close()
        await self._ensure_persistent_browser()
        page = self._page
        assert page is not None

        logger.info("Opening CVS login for manual authentication: %s", CVS_LOGIN_URL)
        try:
            await page.goto(CVS_LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
        except Exception as e:
            logger.error("Failed to open CVS login page: %s", e)
            return {"status": "error", "message": f"Could not open CVS login page: {e}"}

        self._manual_login_active = True
        logger.info("Browser opened for manual login -- user must complete login in the browser")
        return {"status": "browser_opened"}

    async def poll_auth_status(self) -> dict[str, Any]:
        """Check if the user has completed manual login by inspecting cookies/introspect.

        Returns:
            {"status": "pending"} -- user hasn't completed login yet
            {"status": "authenticated", "cookies": {...}} -- login complete
            {"status": "error", ...} -- browser was closed or is dead
        """
        if self._page is None or self._context is None:
            return {"status": "error", "message": "No browser session active"}

        # Check the browser/page is still alive before doing anything
        try:
            await self._page.evaluate("1")
        except Exception:
            logger.warning("Browser is no longer alive during poll")
            return {"status": "error", "message": "Browser window was closed. Please try logging in again."}

        cookies = await self.get_cookies()
        if not cookies:
            return {"status": "pending"}

        introspect_ok = await self._check_introspect(cookies)
        if introspect_ok:
            self._manual_login_active = False
            logger.info("Manual login detected as complete via introspect")
            return {"status": "authenticated", "cookies": cookies}

        # Fallback: check if the page URL navigated away from the login page,
        # which usually indicates a successful login redirect.
        try:
            current_url = self._page.url
            login_pages = ("account-login", "one-time-passcode", "verify-user")
            if not any(frag in current_url for frag in login_pages):
                logger.info("Page URL left login flow (%s), rechecking cookies...", current_url)
                # Re-fetch cookies after potential delayed cookie setting
                cookies = await self.get_cookies()
                if cookies:
                    self._manual_login_active = False
                    return {"status": "authenticated", "cookies": cookies}
        except Exception:
            pass

        return {"status": "pending"}

    async def get_cookies(self) -> dict[str, str]:
        """Extract all CVS cookies from the browser context."""
        if self._context is None:
            return {}
        browser_cookies = await self._context.cookies()
        cookies: dict[str, str] = {}
        for c in browser_cookies:
            if "cvs.com" in c.get("domain", ""):
                cookies[c["name"]] = c["value"]
        return cookies

    async def _check_introspect(self, cookies: dict[str, str]) -> bool:
        """Quick introspect check using the browser's fetch API."""
        if self._page is None:
            return False
        try:
            result = await self._page.evaluate("""
                async () => {
                    try {
                        const resp = await fetch('/api/retail/token/v1/introspect', {
                            method: 'GET',
                            headers: {
                                'Accept': 'application/json',
                                'Content-Type': 'application/json',
                                'x-api-key': 'cnkL3GygZ8GgwivKfflt4q9R9UuROI4M',
                            },
                            credentials: 'include'
                        });
                        if (resp.ok) {
                            const data = await resp.json();
                            return data.statusCode === '0000';
                        }
                        return false;
                    } catch(e) {
                        return false;
                    }
                }
            """)
            return bool(result)
        except Exception as e:
            logger.warning("Browser introspect check failed: %s", e)
            return False

    async def browser_fetch(
        self,
        url: str,
        *,
        method: str = "POST",
        headers: dict[str, str] | None = None,
        body: dict | None = None,
    ) -> dict[str, Any]:
        """Make an API call through the browser's fetch() to preserve Akamai session.

        This is required for authenticated endpoints where cookies alone (without
        matching TLS fingerprint) get rejected by Akamai bot detection.
        """
        if not await self._is_alive():
            raise RuntimeError("Browser is not alive; cannot make authenticated fetch")

        fetch_headers = dict(headers or {})
        fetch_headers.pop("cookie", None)

        js = """
        async ([url, method, headers, body]) => {
            const opts = { method, headers, credentials: 'include' };
            if (body) opts.body = JSON.stringify(body);
            const resp = await fetch(url, opts);
            const text = await resp.text();
            return { status: resp.status, body: text };
        }
        """
        result = await self._page.evaluate(
            js, [url, method, fetch_headers, body]
        )
        status = result["status"]
        try:
            parsed = json.loads(result["body"])
        except (json.JSONDecodeError, TypeError):
            parsed = {"raw": result["body"]}

        if status >= 400:
            logger.warning(
                "Browser fetch %s %s returned %d: %s",
                method, url, status, result["body"][:500],
            )
        return {"status_code": status, "data": parsed}

    async def close(self) -> None:
        """Close the browser and Playwright instance."""
        self._manual_login_active = False
        await self._force_close()


def get_manual_token() -> BootstrapResult | None:
    """
    Fallback: read a manually-provided guest token from environment variable.
    Set CVS_GUEST_TOKEN in .env to bypass Playwright.
    """
    token = os.environ.get("CVS_GUEST_TOKEN", "").strip()
    if not token:
        return None

    logger.info("Using manual CVS_GUEST_TOKEN from environment")
    return BootstrapResult(
        token=token,
        token_expires_at=time.time() + 840,
        cookies={},
        headers={},
    )
