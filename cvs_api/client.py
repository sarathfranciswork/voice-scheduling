"""
CVSClient -- high-level async client for the CVS vaccine scheduling API.

Usage:
    # Auto-bootstrap with Playwright (recommended)
    async with CVSClient(auto_bootstrap=True) as client:
        vaccines = await client.get_eligible_vaccines(date_of_birth="1990-05-15")

    # Manual token from environment
    async with CVSClient(auto_bootstrap=False) as client:
        vaccines = await client.get_eligible_vaccines(date_of_birth="1990-05-15")

    # Authenticated (passwordless: email → OTP → DOB)
    async with CVSClient(auto_bootstrap=True) as client:
        result = await client.login("user@example.com")
        # ... user receives SMS code ...
        otp_result = await client.submit_otp("123456")
        # ... if dob_required ...
        auth = await client.verify_dob("10", "15", "1990")
        profile = await client.get_patient_profile()
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from cvs_api.bootstrap import (
    AuthenticatedBootstrapper,
    PlaywrightBootstrapper,
    get_manual_token,
)
from cvs_api.config import BASE_URL, REQUEST_TIMEOUT_SECONDS
from cvs_api.endpoints import appointments, scheduling, stores, vaccines
from cvs_api.exceptions import AuthenticationError, SessionExpiredError
from cvs_api.session import CVSSession

logger = logging.getLogger(__name__)

BOOTSTRAP_MAX_RETRIES = 3
BOOTSTRAP_RETRY_DELAY_SECONDS = 2


class CVSClient:
    """Async context-managed client wrapping all CVS scheduling API endpoints."""

    def __init__(self, auto_bootstrap: bool | None = None):
        self._session = CVSSession()
        self._http: httpx.AsyncClient | None = None
        self._bootstrapper = PlaywrightBootstrapper()
        self._auth_bootstrapper: AuthenticatedBootstrapper | None = None

        if auto_bootstrap is None:
            auto_bootstrap = os.environ.get("CVS_AUTO_BOOTSTRAP", "true").lower() in ("true", "1", "yes")
        self._auto_bootstrap = auto_bootstrap

    async def __aenter__(self) -> CVSClient:
        await self.bootstrap()
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
            cookies=self._session._cookies if self._session._cookies else None,
        )
        return self

    async def __aexit__(self, *exc):
        if self._http:
            await self._http.aclose()
        if self._auth_bootstrapper:
            await self._auth_bootstrapper.close()
        await self._session.close()

    async def bootstrap(self) -> None:
        """
        Establish a valid CVS session. Tries in order:
        1. Manual token from CVS_GUEST_TOKEN env var
        2. Playwright auto-bootstrap with retries (if enabled)
        3. Direct token acquisition (likely to fail without cookies)
        """
        manual = get_manual_token()
        if manual:
            self._session.inject_bootstrap(manual)
            return

        if self._auto_bootstrap:
            last_error: Exception | None = None
            for attempt in range(1, BOOTSTRAP_MAX_RETRIES + 1):
                try:
                    logger.info(f"Playwright bootstrap attempt {attempt}/{BOOTSTRAP_MAX_RETRIES}")
                    result = await self._bootstrapper.bootstrap()
                    self._session.inject_bootstrap(result)
                    return
                except Exception as e:
                    last_error = e
                    logger.warning(f"Bootstrap attempt {attempt} failed: {e}")
                    if attempt < BOOTSTRAP_MAX_RETRIES:
                        delay = BOOTSTRAP_RETRY_DELAY_SECONDS * attempt
                        logger.info(f"Retrying in {delay}s...")
                        await asyncio.sleep(delay)

            logger.error(
                f"All {BOOTSTRAP_MAX_RETRIES} bootstrap attempts failed. "
                f"Last error: {last_error}"
            )
            logger.info("Falling back to direct token acquisition")

        try:
            await self._session.ensure_token()
        except Exception as e:
            logger.warning(f"Direct token acquisition failed: {e}")
            logger.warning(
                "Set CVS_GUEST_TOKEN in .env or install Playwright: "
                "pip install playwright && playwright install chromium"
            )

    async def refresh_session(self) -> bool:
        """
        Re-bootstrap the session if it's expired or about to expire.
        Returns True if session is now valid.
        """
        if self._session.token_valid:
            return True

        logger.info("Refreshing CVS session...")

        manual = get_manual_token()
        if manual:
            self._session.inject_bootstrap(manual)
            return True

        if self._auto_bootstrap:
            for attempt in range(1, BOOTSTRAP_MAX_RETRIES + 1):
                try:
                    logger.info(f"Refresh bootstrap attempt {attempt}/{BOOTSTRAP_MAX_RETRIES}")
                    result = await self._bootstrapper.bootstrap()
                    self._session.inject_bootstrap(result)

                    if self._http and not self._http.is_closed:
                        await self._http.aclose()
                    self._http = httpx.AsyncClient(
                        base_url=BASE_URL,
                        timeout=REQUEST_TIMEOUT_SECONDS,
                        follow_redirects=True,
                        cookies=self._session._cookies if self._session._cookies else None,
                    )
                    return True
                except Exception as e:
                    logger.warning(f"Refresh attempt {attempt} failed: {e}")
                    if attempt < BOOTSTRAP_MAX_RETRIES:
                        await asyncio.sleep(BOOTSTRAP_RETRY_DELAY_SECONDS * attempt)

        return False

    @property
    def http(self) -> httpx.AsyncClient:
        assert self._http is not None, "CVSClient must be used as async context manager"
        return self._http

    # ------------------------------------------------------------------
    # Vaccine Eligibility
    # ------------------------------------------------------------------

    async def get_eligible_vaccines(
        self,
        date_of_birth: str,
        flow: str = "VACCINE",
    ) -> dict[str, Any]:
        """Get vaccines the patient is eligible for. DOB format: YYYY-MM-DD."""
        return await vaccines.get_eligible_vaccines(
            self._session, self.http, date_of_birth=date_of_birth, flow=flow
        )

    async def check_vaccine_eligibility(
        self,
        vaccine_eligibility_input: dict,
    ) -> dict[str, Any]:
        """Check detailed vaccine eligibility with screening criteria."""
        return await vaccines.check_vaccine_eligibility(
            self._session, self.http, vaccine_eligibility_input=vaccine_eligibility_input
        )

    # ------------------------------------------------------------------
    # Store Search & Time Slots
    # ------------------------------------------------------------------

    async def search_stores(
        self,
        *,
        address: str,
        date_of_birth: str,
        vaccine_eligibility_data: dict[str, Any],
        vaccine_codes: list[str],
        radius: int = 35,
        max_results: int = 25,
    ) -> dict[str, Any]:
        """Search CVS pharmacies with vaccine availability near a location.

        Requires the full response from check_vaccine_eligibility to build
        the correct search payload with NDC codes and manufacturer data.
        """
        return await stores.search_stores(
            self._session,
            self.http,
            address=address,
            date_of_birth=date_of_birth,
            vaccine_eligibility_data=vaccine_eligibility_data,
            vaccine_codes=vaccine_codes,
            radius=radius,
            max_results=max_results,
        )

    async def get_available_time_slots(
        self,
        *,
        visit_date: str,
        date_of_birth: str,
        vaccine_codes: list[str],
        store_search_results: dict[str, Any],
        vaccine_eligibility_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Get available appointment times for stores on a specific date.

        Requires the full response from both search_stores and
        check_vaccine_eligibility to build the correct payload.
        """
        return await stores.get_available_time_slots(
            self._session,
            self.http,
            visit_date=visit_date,
            date_of_birth=date_of_birth,
            vaccine_codes=vaccine_codes,
            store_search_results=store_search_results,
            vaccine_eligibility_data=vaccine_eligibility_data,
        )

    async def get_store_details(self, store_id: str) -> dict[str, Any]:
        """Retrieve detailed store info (address, hours, phone)."""
        return await stores.get_store_details(self._session, self.http, store_id)

    # ------------------------------------------------------------------
    # Scheduling Workflow
    # ------------------------------------------------------------------

    async def soft_reserve_slot(
        self,
        scheduling_input: dict,
        id_type: str = "refId",
    ) -> dict[str, Any]:
        """Temporarily reserve a time slot while the patient completes registration."""
        return await scheduling.soft_reserve_slot(
            self._session, self.http, scheduling_input=scheduling_input, id_type=id_type
        )

    async def submit_patient_details(
        self,
        patient_details_input: dict,
        id_type: str = "refId",
    ) -> dict[str, Any]:
        """Submit patient demographics (name, DOB, contact, address)."""
        return await scheduling.submit_patient_details(
            self._session, self.http, patient_details_input=patient_details_input, id_type=id_type
        )

    async def get_questionnaire(
        self,
        questionnaire_input: dict,
        id_type: str = "refId",
    ) -> dict[str, Any]:
        """Retrieve the pre-appointment screening questionnaire."""
        return await scheduling.get_questionnaire(
            self._session, self.http, questionnaire_input=questionnaire_input, id_type=id_type
        )

    async def submit_questionnaire(
        self,
        scheduling_questionnaire_input: dict,
        id_type: str = "refId",
    ) -> dict[str, Any]:
        """Submit completed questionnaire answers."""
        return await scheduling.submit_questionnaire(
            self._session,
            self.http,
            scheduling_questionnaire_input=scheduling_questionnaire_input,
            id_type=id_type,
        )

    async def get_user_schedule(
        self,
        check_duplicate: bool = True,
        id_type: str = "refId",
    ) -> dict[str, Any]:
        """Check for existing scheduled appointments (duplicate check)."""
        return await scheduling.get_user_schedule(
            self._session, self.http, check_duplicate=check_duplicate, id_type=id_type
        )

    async def confirm_appointment(
        self,
        confirm_appointment_input: dict,
    ) -> dict[str, Any]:
        """Final appointment confirmation -- returns confirmation number."""
        return await scheduling.confirm_appointment(
            self._session, self.http, confirm_appointment_input=confirm_appointment_input
        )

    async def address_typeahead(
        self,
        search_text: str,
        max_results: int = 5,
    ) -> dict[str, Any]:
        """Address autocomplete for patient address entry."""
        return await scheduling.address_typeahead(
            self._session, self.http, search_text=search_text, max_results=max_results
        )

    # ------------------------------------------------------------------
    # Authentication (OTP, Password, or Manual browser login)
    # ------------------------------------------------------------------

    def _ensure_auth_bootstrapper(self, headless: bool = False) -> AuthenticatedBootstrapper:
        if self._auth_bootstrapper is None:
            self._auth_bootstrapper = AuthenticatedBootstrapper(headless=headless)
        return self._auth_bootstrapper

    def _handle_auth_success(self, cookies: dict[str, str]) -> None:
        self._session.inject_auth_cookies(cookies)
        self._rebuild_http()

    async def login(self, email: str) -> dict[str, Any]:
        """OTP flow step 1: enters email, sends OTP via SMS."""
        bootstrapper = self._ensure_auth_bootstrapper()
        result = await bootstrapper.start_login(email)
        if result.get("status") == "authenticated":
            self._handle_auth_success(result.get("cookies", {}))
        return result

    async def login_with_password(self, email: str, password: str) -> dict[str, Any]:
        """Password flow: enters email, navigates to password page, submits password."""
        bootstrapper = self._ensure_auth_bootstrapper()
        result = await bootstrapper.start_login_with_password(email, password)
        if result.get("status") == "authenticated":
            self._handle_auth_success(result.get("cookies", {}))
        return result

    async def start_manual_login(self) -> dict[str, Any]:
        """Open CVS login page for the user to complete login manually in the browser."""
        bootstrapper = self._ensure_auth_bootstrapper()
        return await bootstrapper.open_for_manual_login()

    async def check_login_status(self) -> dict[str, Any]:
        """Poll whether the user has completed manual login."""
        if self._auth_bootstrapper is None:
            return {"status": "error", "message": "No login session active"}
        result = await self._auth_bootstrapper.poll_auth_status()
        if result.get("status") == "authenticated":
            self._handle_auth_success(result.get("cookies", {}))
        return result

    async def logout(self) -> dict[str, Any]:
        """Clear authenticated session and close the auth browser."""
        self._session.clear_auth()
        if self._auth_bootstrapper:
            await self._auth_bootstrapper.close()
            self._auth_bootstrapper = None
        self._rebuild_http()
        return {"status": "logged_out"}

    async def submit_otp(self, code: str) -> dict[str, Any]:
        """Step 2: Submit the 6-digit OTP code.

        Returns:
            {"status": "dob_required"} if DOB verification is needed next
            {"status": "authenticated", ...} if auth completed without DOB
        """
        if self._auth_bootstrapper is None:
            raise AuthenticationError("No active login session. Call login() first.")

        result = await self._auth_bootstrapper.submit_otp(code)

        if result.get("status") == "authenticated":
            cookies = result.get("cookies", {})
            self._session.inject_auth_cookies(cookies)
            self._rebuild_http()

        return result

    async def verify_dob(self, month: str, day: str, year: str) -> dict[str, Any]:
        """Step 3: Enter date of birth to complete authentication.

        Args:
            month: Two-digit month (e.g. "10")
            day: Two-digit day (e.g. "05")
            year: Four-digit year (e.g. "1990")
        """
        if self._auth_bootstrapper is None:
            raise AuthenticationError("No active login session.")

        result = await self._auth_bootstrapper.verify_dob(month, day, year)

        if result.get("status") == "authenticated":
            cookies = result.get("cookies", {})
            self._session.inject_auth_cookies(cookies)
            self._rebuild_http()

            verified = await self._session.introspect()
            if verified:
                logger.info("Authenticated session verified via introspect")
            else:
                logger.warning("Introspect did not confirm authentication")

        return result

    def _rebuild_http(self) -> None:
        """Recreate the httpx client with updated cookies."""
        if self._http and not self._http.is_closed:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._http.aclose())
            except RuntimeError:
                pass
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
            cookies=self._session._cookies if self._session._cookies else None,
        )

    # ------------------------------------------------------------------
    # Authenticated API transport
    # ------------------------------------------------------------------

    async def auth_post(
        self,
        path: str,
        *,
        headers: dict[str, str],
        body: dict,
    ) -> dict[str, Any]:
        """Make an authenticated POST request through the Playwright browser.

        Akamai ties session cookies to the browser's TLS fingerprint, so
        authenticated calls (which rely on cookies rather than Bearer tokens)
        must go through the same browser that performed login.
        Falls back to httpx if the browser is unavailable.
        """
        url = f"{BASE_URL}{path}"

        if self._auth_bootstrapper and await self._auth_bootstrapper._is_alive():
            result = await self._auth_bootstrapper.browser_fetch(
                url, method="POST", headers=headers, body=body,
            )
            status = result["status_code"]
            data = result["data"]
            if status >= 400:
                from cvs_api.exceptions import CVSAPIError
                raise CVSAPIError(
                    f"Authenticated API returned HTTP {status} for {path}",
                    status_code=status,
                    response_body=data,
                )
            return data

        if self._session.is_authenticated:
            from cvs_api.exceptions import AuthenticationError
            raise AuthenticationError(
                "Login browser session has expired. Please log in again via the "
                "Login button to use authenticated features."
            )

        logger.warning("Auth browser unavailable, falling back to httpx for %s", path)
        resp = await self.http.post(path, json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Authenticated Endpoints
    # ------------------------------------------------------------------

    async def get_patient_profile(self) -> dict[str, Any]:
        """Fetch the authenticated user's patient profile."""
        return await appointments.get_patient_profile(self._session, self.auth_post)

    async def get_upcoming_appointments(
        self, lob_list: list[str] | None = None
    ) -> dict[str, Any]:
        """Fetch the authenticated user's upcoming appointments."""
        return await appointments.get_upcoming_appointments(
            self._session, self.auth_post, lob_list=lob_list
        )

    async def cancel_appointment(
        self,
        *,
        lob: str,
        cancel_reason_code: str = "8",
        vaccine_ids: list[str],
        confirmation_number: str,
    ) -> dict[str, Any]:
        """Cancel an existing appointment."""
        return await appointments.cancel_appointment(
            self._session,
            self.auth_post,
            lob=lob,
            cancel_reason_code=cancel_reason_code,
            vaccine_ids=vaccine_ids,
            confirmation_number=confirmation_number,
        )
