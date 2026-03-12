"""
CVS API session manager -- handles guest token lifecycle, fingerprinting, and common headers.

Supports three modes:
  1. Bootstrapped: token + cookies injected from PlaywrightBootstrapper (guest)
  2. Direct: self-acquires token via /api/guest/v1/token (may fail without browser cookies)
  3. Authenticated: cookies from CVS login (for profile, appointments, cancellation)
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from typing import TYPE_CHECKING

import httpx

from cvs_api.config import (
    BASE_URL,
    DEFAULT_TOKEN_TTL_SECONDS,
    EXPERIENCE_API_KEY,
    INTROSPECT_API_KEY,
    INTROSPECT_PATH,
    REQUEST_TIMEOUT_SECONDS,
    TOKEN_API_KEY,
    TOKEN_PATH,
    TOKEN_REFRESH_BUFFER_SECONDS,
)
from cvs_api.exceptions import AuthenticationError, SessionExpiredError, TokenError

if TYPE_CHECKING:
    from cvs_api.bootstrap import BootstrapResult

logger = logging.getLogger(__name__)


class CVSSession:
    """Manages guest token acquisition, refresh, and common request state."""

    def __init__(self):
        self._http: httpx.AsyncClient | None = None
        self._token: str | None = None
        self._token_expires_at: float = 0
        self._visitor_id: str = str(uuid.uuid4())
        self._experience_id: str = str(uuid.uuid4())
        self._client_ref_id: str = str(uuid.uuid4())
        self._fingerprint: str = self._generate_fingerprint()
        self._cookies: dict[str, str] = {}
        self._bootstrapped: bool = False
        self._authenticated: bool = False
        self._extra_headers: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Guest bootstrap
    # ------------------------------------------------------------------

    def inject_bootstrap(self, result: BootstrapResult) -> None:
        """Inject token, cookies, and headers from a Playwright bootstrap."""
        self._token = result.token
        self._token_expires_at = result.token_expires_at
        self._cookies = dict(result.cookies)
        self._bootstrapped = True

        if result.headers.get("x-visitor-id"):
            self._visitor_id = result.headers["x-visitor-id"]
        if result.headers.get("x-experienceid"):
            self._experience_id = result.headers["x-experienceid"]

        self._extra_headers = {
            k: v for k, v in result.headers.items()
            if k not in ("x-visitor-id", "x-experienceid")
        }

        self._invalidate_http()

        logger.info(
            f"Session bootstrapped: token valid for "
            f"{int(self._token_expires_at - time.time())}s, "
            f"{len(self._cookies)} cookies injected"
        )

    # ------------------------------------------------------------------
    # Authenticated session (CVS login cookies)
    # ------------------------------------------------------------------

    def inject_auth_cookies(self, cookies: dict[str, str]) -> None:
        """Merge authenticated browser cookies into the session."""
        self._cookies.update(cookies)
        self._authenticated = True
        self._invalidate_http()
        logger.info(
            "Authenticated cookies injected (%d total cookies)", len(self._cookies)
        )

    def clear_auth(self) -> None:
        """Clear authenticated state (logout)."""
        self._authenticated = False
        logger.info("Authenticated session cleared")

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    async def introspect(self) -> bool:
        """Verify the authenticated session via the retail token introspect endpoint.

        Returns True if the session cookies represent a valid logged-in user.
        """
        http = await self._get_http()
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "x-api-key": INTROSPECT_API_KEY,
            "origin": "https://www.cvs.com",
            "referer": "https://www.cvs.com/",
        }
        try:
            resp = await http.get(INTROSPECT_PATH, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            success = data.get("statusCode") == "0000"
            if success:
                logger.info("Introspect confirmed: authenticated session is valid")
            else:
                logger.warning("Introspect returned non-success: %s", data)
            return success
        except Exception as e:
            logger.warning("Introspect call failed: %s", e)
            return False

    def get_auth_experience_headers(
        self,
        experience_name: str,
        experience_uuid: str,
        *,
        route: str = "I90health",
        category: str = "NGS_CANCEL_RESCH",
        client_id: str | None = None,
        referer: str = "https://www.cvs.com/scheduling/cancel/upcoming-visits?lob=rximz&flow=cancel_resch",
    ) -> dict[str, str]:
        """Build headers for an authenticated experience API call.

        Different endpoints require different routing headers:
          - patientProfile: route=PHARMACY-GKE-RKE, client_id=imz
          - upcomingAppointments / cancelAppointment: route=I90health
        """
        if not self._authenticated:
            raise AuthenticationError("Not authenticated. Call login first.")

        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "x-api-key": EXPERIENCE_API_KEY,
            "x-experience-name": experience_name,
            "x-experienceid": experience_uuid,
            "x-client-fingerprint-id": self._fingerprint,
            "x-clientrefid": str(uuid.uuid4()),
            "x-route": route,
            "api-key": "experienceUrl",
            "access-control-expose-headers": "grid",
            "cat": category,
            "category": category,
            "x-cat": "NGS_WEB",
            "adrum": "isAjax:true",
            "x-channel": "WEB",
            "origin": "https://www.cvs.com",
            "referer": referer,
        }
        if client_id:
            headers["x-clientid"] = client_id
        return headers

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_bootstrapped(self) -> bool:
        return self._bootstrapped

    @property
    def token_valid(self) -> bool:
        return bool(self._token) and time.time() < self._token_expires_at

    # ------------------------------------------------------------------
    # HTTP client management
    # ------------------------------------------------------------------

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=BASE_URL,
                timeout=REQUEST_TIMEOUT_SECONDS,
                follow_redirects=True,
                http2=False,
                cookies=self._cookies if self._cookies else None,
            )
        return self._http

    def _invalidate_http(self) -> None:
        """Close the existing HTTP client so it gets recreated with fresh cookies."""
        if self._http and not self._http.is_closed:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._http.aclose())
            except RuntimeError:
                pass
        self._http = None

    # ------------------------------------------------------------------
    # Fingerprint / token
    # ------------------------------------------------------------------

    def _generate_fingerprint(self) -> str:
        canvas = hashlib.sha256(self._visitor_id.encode()).hexdigest()
        return canvas

    async def ensure_token(self) -> str:
        """Return a valid guest token, refreshing if needed."""
        if self._token and time.time() < self._token_expires_at:
            return self._token

        if self._bootstrapped:
            raise SessionExpiredError(
                "Bootstrapped token has expired. Re-bootstrap required."
            )

        return await self._refresh_token()

    async def _refresh_token(self) -> str:
        """Attempt direct token acquisition (works only with valid cookies)."""
        http = await self._get_http()

        headers = {
            "content-type": "application/json",
            "accept": "*/*",
            "x-visitor-id": self._visitor_id,
            "x-api-key": TOKEN_API_KEY,
            "x-experienceid": self._experience_id,
            "x-channel": "WEB",
            "origin": "https://www.cvs.com",
            "referer": "https://www.cvs.com/",
        }
        headers.update(self._extra_headers)

        body = {"data": {"cp": self._fingerprint}}

        try:
            resp = await http.post(TOKEN_PATH, json=body, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise TokenError(
                f"Token request failed: HTTP {e.response.status_code}",
                status_code=e.response.status_code,
            ) from e
        except httpx.RequestError as e:
            raise TokenError(f"Token request error: {e}") from e

        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise TokenError("No access_token in response", response_body=data)

        ttl = int(data.get("expires_in", DEFAULT_TOKEN_TTL_SECONDS))
        self._token = token
        self._token_expires_at = time.time() + ttl - TOKEN_REFRESH_BUFFER_SECONDS

        return token

    # ------------------------------------------------------------------
    # Header builders
    # ------------------------------------------------------------------

    def get_experience_headers(self, experience_name: str, experience_uuid: str) -> dict[str, str]:
        """Build the headers dict for a guest experience API call."""
        if not self._token:
            raise SessionExpiredError("No token available. Call ensure_token() first.")

        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "authorization": f"Bearer {self._token}",
            "x-api-key": EXPERIENCE_API_KEY,
            "x-experience-name": experience_name,
            "x-experienceid": experience_uuid,
            "x-client-fingerprint-id": self._fingerprint,
            "x-clientrefid": self._client_ref_id,
            "x-route": "I90health",
            "api-key": "experienceUrl",
            "access-control-expose-headers": "grid",
            "cat": "NGS_IMZ",
            "category": "NGS_IMZ",
            "x-cat": "NGS_WEB",
            "adrum": "isAjax:true",
            "x-channel": "WEB",
            "origin": "https://www.cvs.com",
            "referer": "https://www.cvs.com/",
        }
        headers.update(self._extra_headers)
        return headers

    async def close(self):
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None
