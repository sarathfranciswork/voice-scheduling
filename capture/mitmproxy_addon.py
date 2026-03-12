"""
Smart mitmproxy addon for capturing CVS vaccine scheduling API calls.

Automatically filters out noise (analytics, CDN, static assets, tracking)
and captures only relevant scheduling API requests with full details.

Key features:
  - Smart noise filtering (55+ exclusion patterns)
  - CVS experience API recognition (UUID-based /scheduling/client/experience/v2/)
  - Token lifecycle tracking (captures token from /api/guest/v1/token and links
    it to every subsequent API call that uses it)
  - Content-aware labeling (inspects response body to label experience API steps)
  - Full request/response recording with auth context

Usage:
    mitmweb --scripts capture/mitmproxy_addon.py
    mitmproxy --scripts capture/mitmproxy_addon.py
    mitmdump --scripts capture/mitmproxy_addon.py

All configuration is in capture/config.py -- edit include/exclude patterns there.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from mitmproxy import ctx, http

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from capture.config import (
    API_CATALOG_PATH,
    AUTH_HEADERS,
    EXCLUDE_DOMAIN_KEYWORDS,
    EXCLUDE_METHODS,
    EXCLUDE_PATH_KEYWORDS,
    EXCLUDE_PATH_SUFFIXES,
    INCLUDE_CONTENT_TYPES,
    INCLUDE_DOMAIN_KEYWORDS,
    INCLUDE_METHODS_ALWAYS,
    INCLUDE_PATH_HIGH_PRIORITY,
    INCLUDE_PATH_KEYWORDS,
    RAW_FLOWS_DIR,
    SANITIZE_HEADERS,
    TOKEN_ENDPOINT_PATHS,
    TOKEN_RESPONSE_KEYS,
)

# Regex to detect UUID in URL paths
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


class CVSCapture:
    """Mitmproxy addon that captures and catalogs CVS scheduling API calls."""

    def __init__(self):
        self.step_counter = 0
        self.captured_flows: list[dict] = []
        self.output_dir = _project_root / RAW_FLOWS_DIR
        self.catalog_path = _project_root / API_CATALOG_PATH
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        self._start_time = time.monotonic()

        # Token tracking state
        self._current_token: str | None = None
        self._token_step: int | None = None
        self._token_type: str | None = None
        self._tokens_seen: list[dict] = []

        # Experience API UUID -> label mapping (built up as we see responses)
        self._uuid_labels: dict[str, str] = {}

    def load(self, loader):
        ctx.log.info("=" * 64)
        ctx.log.info("  CVS Vaccine Scheduling API Capture Addon v2")
        ctx.log.info("=" * 64)
        ctx.log.info(f"  Output dir:    {self.output_dir}")
        ctx.log.info(f"  Catalog:       {self.catalog_path}")
        ctx.log.info(f"  Filtering:     ON (see capture/config.py)")
        ctx.log.info(f"  Token tracking: ON")
        ctx.log.info(f"  Experience API: auto-detect + content-aware labeling")
        ctx.log.info("")
        ctx.log.info("  Navigate the CVS scheduling flow in your browser.")
        ctx.log.info("  Relevant API calls will be auto-captured.")
        ctx.log.info("  Press Ctrl+C to finalize the catalog.")
        ctx.log.info("=" * 64)

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _should_exclude(self, flow: http.HTTPFlow) -> bool:
        req = flow.request
        url_lower = req.pretty_url.lower()
        path_lower = req.path.lower()

        if req.method.upper() in EXCLUDE_METHODS:
            return True

        for kw in EXCLUDE_DOMAIN_KEYWORDS:
            if kw in url_lower:
                return True

        for suffix in EXCLUDE_PATH_SUFFIXES:
            if path_lower.endswith(suffix):
                return True
            query_stripped = path_lower.split("?")[0]
            if query_stripped.endswith(suffix):
                return True

        for kw in EXCLUDE_PATH_KEYWORDS:
            if kw in path_lower:
                return True

        return False

    def _should_include(self, flow: http.HTTPFlow) -> bool:
        req = flow.request
        url_lower = req.pretty_url.lower()
        path_lower = req.path.lower()

        domain_match = any(kw in url_lower for kw in INCLUDE_DOMAIN_KEYWORDS)
        if not domain_match:
            return False

        for hp in INCLUDE_PATH_HIGH_PRIORITY:
            if hp in path_lower:
                return True

        if req.method.upper() in INCLUDE_METHODS_ALWAYS:
            return True

        for kw in INCLUDE_PATH_KEYWORDS:
            if kw in path_lower:
                return True

        resp = flow.response
        if resp:
            ct = resp.headers.get("content-type", "").lower()
            if any(inc_ct in ct for inc_ct in INCLUDE_CONTENT_TYPES):
                if req.method.upper() in ("GET",) and "api" in path_lower:
                    return True

        return False

    # ------------------------------------------------------------------
    # Token tracking
    # ------------------------------------------------------------------

    def _is_token_endpoint(self, path: str) -> bool:
        path_lower = path.lower()
        return any(tp in path_lower for tp in TOKEN_ENDPOINT_PATHS)

    def _extract_token_from_response(self, body: dict | list | str | None) -> str | None:
        if not isinstance(body, dict):
            return None
        for key_path in TOKEN_RESPONSE_KEYS:
            val = body
            for key in key_path:
                if isinstance(val, dict) and key in val:
                    val = val[key]
                else:
                    val = None
                    break
            if isinstance(val, str) and len(val) > 10:
                return val
        return None

    def _get_auth_context(self, req: http.Request) -> dict:
        """Extract auth-related headers from the request for tracking."""
        auth_info: dict[str, str] = {}
        for header_name in AUTH_HEADERS:
            val = req.headers.get(header_name)
            if val:
                auth_info[header_name] = val

        result: dict = {"headers": auth_info if auth_info else None}

        if self._current_token:
            auth_header = req.headers.get("authorization", "")
            if self._current_token in auth_header:
                result["uses_captured_token"] = True
                result["token_from_step"] = self._token_step
            else:
                for hdr_name in AUTH_HEADERS:
                    hdr_val = req.headers.get(hdr_name, "")
                    if self._current_token in hdr_val:
                        result["uses_captured_token"] = True
                        result["token_from_step"] = self._token_step
                        result["token_in_header"] = hdr_name
                        break

        return result

    # ------------------------------------------------------------------
    # Experience API labeling
    # ------------------------------------------------------------------

    def _extract_uuid_from_path(self, path: str) -> str | None:
        match = _UUID_RE.search(path)
        return match.group(0) if match else None

    def _is_experience_api(self, path: str) -> bool:
        return "/scheduling/client/experience/" in path.lower()

    def _label_experience_api(
        self, req: http.Request, resp_body: dict | list | str | None
    ) -> str:
        """Label an experience API call by inspecting the response content."""
        method = req.method.upper()
        uuid = self._extract_uuid_from_path(req.path)

        if uuid and uuid in self._uuid_labels:
            return f"{method.lower()}_experience_{self._uuid_labels[uuid]}"

        label_suffix = self._infer_experience_step(req, resp_body)

        if uuid:
            self._uuid_labels[uuid] = label_suffix

        return f"{method.lower()}_experience_{label_suffix}"

    def _infer_experience_step(
        self, req: http.Request, resp_body: dict | list | str | None
    ) -> str:
        """Infer the scheduling step from request/response body content."""
        texts_to_search: list[str] = []

        req_body = self._try_parse_json(req.content)
        if isinstance(req_body, dict):
            texts_to_search.append(json.dumps(req_body).lower())
        if isinstance(resp_body, dict):
            texts_to_search.append(json.dumps(resp_body).lower())

        combined = " ".join(texts_to_search)

        inference_rules = [
            (["token", "auth"], "token"),
            (["store", "location"], "store_selection"),
            (["address", "zip", "postal"], "location_search"),
            (["vaccine", "type", "immunization"], "vaccine_type"),
            (["vaccine", "select"], "vaccine_selection"),
            (["eligib"], "eligibility"),
            (["available", "date"], "date_availability"),
            (["slot", "time"], "time_slots"),
            (["time", "available"], "time_slots"),
            (["appointment", "slot"], "appointment_slots"),
            (["patient", "name", "first"], "patient_info"),
            (["patient", "info"], "patient_info"),
            (["insurance", "carrier"], "insurance_info"),
            (["consent", "agree"], "consent"),
            (["confirm", "book"], "booking_confirmation"),
            (["confirm", "appointment"], "appointment_confirmation"),
            (["review", "summary"], "review"),
            (["schedule", "confirm"], "schedule_confirm"),
            (["question", "screen"], "screening_questions"),
            (["screen"], "screening"),
        ]

        for keywords, label in inference_rules:
            if all(kw in combined for kw in keywords):
                return label

        uuid = self._extract_uuid_from_path(req.path)
        return f"uuid_{uuid[:8]}" if uuid else "unknown"

    # ------------------------------------------------------------------
    # Sanitization & parsing
    # ------------------------------------------------------------------

    def _sanitize_headers(self, headers: dict[str, str]) -> dict[str, str]:
        sanitized = {}
        for k, v in headers.items():
            if k.lower() in SANITIZE_HEADERS:
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = v
        return sanitized

    def _try_parse_json(self, content: bytes | None) -> str | dict | list | None:
        if not content:
            return None
        try:
            return json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError):
            try:
                return content.decode("utf-8", errors="replace")[:2000]
            except Exception:
                return f"[binary, {len(content)} bytes]"

    # ------------------------------------------------------------------
    # Main capture
    # ------------------------------------------------------------------

    def response(self, flow: http.HTTPFlow):
        if self._should_exclude(flow):
            return
        if not self._should_include(flow):
            return

        self.step_counter += 1
        step_num = self.step_counter

        req = flow.request
        resp = flow.response

        parsed_url = urlparse(req.pretty_url)
        elapsed = time.monotonic() - self._start_time

        resp_body = self._try_parse_json(resp.content) if resp else None
        req_body = self._try_parse_json(req.content)

        # --- Token tracking ---
        is_token = self._is_token_endpoint(req.path)
        token_info: dict | None = None

        if is_token and resp_body:
            extracted = self._extract_token_from_response(resp_body)
            if extracted:
                self._current_token = extracted
                self._token_step = step_num
                token_preview = extracted[:20] + "..." if len(extracted) > 20 else extracted
                token_info = {
                    "is_token_endpoint": True,
                    "token_extracted": True,
                    "token_preview": token_preview,
                    "token_length": len(extracted),
                }
                self._tokens_seen.append({
                    "step": step_num,
                    "preview": token_preview,
                })
                ctx.log.info(f"  [TOKEN] Captured auth token at step {step_num}: {token_preview}")
            else:
                token_info = {
                    "is_token_endpoint": True,
                    "token_extracted": False,
                    "note": "Could not find token in response. Check TOKEN_RESPONSE_KEYS in config.",
                }

        # --- Auth context for non-token calls ---
        auth_context = self._get_auth_context(req)

        # --- Labeling ---
        if is_token:
            label = f"{req.method.lower()}_guest_token"
        elif self._is_experience_api(req.path):
            label = self._label_experience_api(req, resp_body)
        else:
            label = self._auto_label(req)

        # --- Build record ---
        record = {
            "step": step_num,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed, 2),
            "label": label,
            "api_type": self._classify_api_type(req.path),
            "request": {
                "method": req.method,
                "url": req.pretty_url,
                "host": parsed_url.hostname,
                "path": parsed_url.path,
                "query": parsed_url.query or None,
                "headers": self._sanitize_headers(dict(req.headers)),
                "body": req_body,
            },
            "response": {
                "status_code": resp.status_code if resp else None,
                "headers": self._sanitize_headers(dict(resp.headers)) if resp else {},
                "body": resp_body,
            },
            "auth": auth_context,
        }

        if token_info:
            record["token_info"] = token_info

        uuid = self._extract_uuid_from_path(req.path)
        if uuid:
            record["experience_uuid"] = uuid

        self.captured_flows.append(record)

        filename = f"step_{step_num:03d}_{label}.json"
        filepath = self.output_dir / filename
        with open(filepath, "w") as f:
            json.dump(record, f, indent=2, default=str)

        token_marker = ""
        if auth_context.get("uses_captured_token"):
            token_marker = f" [token from step {auth_context.get('token_from_step')}]"
        if is_token:
            token_marker = " [TOKEN ENDPOINT]"

        ctx.log.info(
            f"[CAPTURED #{step_num}] {req.method} {parsed_url.path[:80]} "
            f"-> {resp.status_code if resp else '???'} "
            f"({label}){token_marker}"
        )

        self._update_catalog()

    def _classify_api_type(self, path: str) -> str:
        path_lower = path.lower()
        if self._is_token_endpoint(path_lower):
            return "token"
        if self._is_experience_api(path_lower):
            return "experience"
        if "/api/" in path_lower:
            return "api"
        if "/scheduling/" in path_lower:
            return "scheduling"
        return "other"

    def _auto_label(self, req: http.Request) -> str:
        """Fallback label for non-experience, non-token API calls."""
        path = req.path.lower()
        method = req.method.upper()

        label_map = [
            (["store", "location", "search"], "store_search"),
            (["store", "detail"], "store_details"),
            (["vaccine", "type"], "vaccine_types"),
            (["immunization", "type"], "vaccine_types"),
            (["availab"], "availability_check"),
            (["time", "slot"], "time_slots"),
            (["slot"], "time_slots"),
            (["schedule"], "scheduling"),
            (["book", "appointment"], "book_appointment"),
            (["appointment"], "appointment"),
            (["patient", "info"], "patient_info"),
            (["patient"], "patient"),
            (["eligib"], "eligibility_check"),
            (["intake"], "intake"),
            (["session"], "session"),
            (["auth", "token"], "auth_token"),
            (["auth"], "auth"),
            (["confirm"], "confirmation"),
            (["cancel"], "cancellation"),
            (["immunization"], "immunization"),
            (["guest"], "guest"),
        ]

        for keywords, label in label_map:
            if all(kw in path for kw in keywords):
                return f"{method.lower()}_{label}"

        slug = (
            req.path.strip("/")
            .split("/")[-1]
            .split("?")[0]
            .replace("-", "_")
            .replace(".", "_")
        )
        if not slug or _UUID_RE.fullmatch(slug):
            parts = [p for p in req.path.strip("/").split("/") if not _UUID_RE.fullmatch(p)]
            slug = parts[-1] if parts else "root"
            slug = slug.replace("-", "_").replace(".", "_")
        return f"{method.lower()}_{slug[:40]}"

    # ------------------------------------------------------------------
    # Catalog generation
    # ------------------------------------------------------------------

    def _update_catalog(self):
        catalog = {
            "description": "CVS Vaccine Scheduling API Catalog",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_captured": len(self.captured_flows),
            "token_endpoints": self._tokens_seen,
            "experience_uuids": dict(self._uuid_labels),
            "endpoints": [],
        }

        seen_endpoints: dict[str, dict] = {}

        for record in self.captured_flows:
            req = record["request"]
            api_type = record.get("api_type", "other")

            if api_type == "experience":
                key = f"{req['method']} experience:{record.get('label', 'unknown')}"
            else:
                key = f"{req['method']} {req['path']}"

            if key not in seen_endpoints:
                seen_endpoints[key] = {
                    "method": req["method"],
                    "path": req["path"],
                    "host": req["host"],
                    "full_url_example": req["url"],
                    "label": record["label"],
                    "api_type": api_type,
                    "experience_uuid": record.get("experience_uuid"),
                    "requires_token": bool(
                        record.get("auth", {}).get("uses_captured_token")
                    ),
                    "occurrences": [],
                }

            seen_endpoints[key]["occurrences"].append({
                "step": record["step"],
                "timestamp": record["timestamp"],
                "query": req.get("query"),
                "request_body_sample": _truncate(req.get("body")),
                "response_status": record["response"]["status_code"],
                "response_body_sample": _truncate(record["response"].get("body")),
                "auth": _truncate(record.get("auth")),
            })

        catalog["endpoints"] = list(seen_endpoints.values())

        with open(self.catalog_path, "w") as f:
            json.dump(catalog, f, indent=2, default=str)

    def done(self):
        self._update_catalog()

        ctx.log.info("")
        ctx.log.info("=" * 64)
        ctx.log.info(f"  Capture complete! {self.step_counter} API calls recorded.")
        ctx.log.info(f"  Individual flows:    {self.output_dir}/")
        ctx.log.info(f"  API catalog:         {self.catalog_path}")
        ctx.log.info("")

        if self._tokens_seen:
            ctx.log.info(f"  Tokens captured:     {len(self._tokens_seen)}")
            for t in self._tokens_seen:
                ctx.log.info(f"    Step {t['step']}: {t['preview']}")
        else:
            ctx.log.info("  Tokens captured:     NONE (check TOKEN_ENDPOINT_PATHS in config)")

        if self._uuid_labels:
            ctx.log.info(f"  Experience UUIDs:    {len(self._uuid_labels)}")
            for uuid, label in self._uuid_labels.items():
                ctx.log.info(f"    {uuid[:8]}... -> {label}")
        else:
            ctx.log.info("  Experience UUIDs:    NONE")

        ctx.log.info("")

        exp_flows = [f for f in self.captured_flows if f.get("api_type") == "experience"]
        token_flows = [f for f in self.captured_flows if f.get("api_type") == "token"]
        other_flows = [f for f in self.captured_flows
                       if f.get("api_type") not in ("experience", "token")]

        ctx.log.info(f"  Breakdown:")
        ctx.log.info(f"    Token calls:       {len(token_flows)}")
        ctx.log.info(f"    Experience calls:   {len(exp_flows)}")
        ctx.log.info(f"    Other API calls:    {len(other_flows)}")
        ctx.log.info("")
        ctx.log.info("  Next steps:")
        ctx.log.info("    1. python capture/analyze_capture.py")
        ctx.log.info("    2. Review docs/api_catalog.json")
        ctx.log.info("    3. Edit docs/USER_JOURNEY.md")
        ctx.log.info("=" * 64)


def _truncate(obj, max_keys=10, max_str_len=500):
    """Truncate large JSON bodies for the catalog summary."""
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj[:max_str_len] + ("..." if len(obj) > max_str_len else "")
    if isinstance(obj, dict):
        items = list(obj.items())[:max_keys]
        result = {k: _truncate(v, max_keys, max_str_len) for k, v in items}
        if len(obj) > max_keys:
            result["__truncated__"] = f"{len(obj) - max_keys} more keys"
        return result
    if isinstance(obj, list):
        if len(obj) > 3:
            return [
                _truncate(obj[0], max_keys, max_str_len),
                f"... {len(obj) - 1} more items",
            ]
        return [_truncate(item, max_keys, max_str_len) for item in obj]
    return obj


addons = [CVSCapture()]
