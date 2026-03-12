#!/usr/bin/env python3
"""
Post-capture analysis tool.

Run after the mitmproxy capture session to generate a human-readable
summary and a USER_JOURNEY.md template.

Usage:
    python capture/analyze_capture.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_FLOWS_DIR = PROJECT_ROOT / "capture" / "raw_flows"
CATALOG_PATH = PROJECT_ROOT / "docs" / "api_catalog.json"
JOURNEY_PATH = PROJECT_ROOT / "docs" / "USER_JOURNEY.md"


def load_flows() -> list[dict]:
    flows = []
    for p in sorted(RAW_FLOWS_DIR.glob("step_*.json")):
        with open(p) as f:
            flows.append(json.load(f))
    return flows


def print_summary(flows: list[dict]):
    print(f"\n{'='*70}")
    print(f"  CVS Vaccine Scheduling -- Captured API Calls Summary")
    print(f"  Total: {len(flows)} calls")
    print(f"{'='*70}\n")

    # Token flow summary
    token_flows = [f for f in flows if f.get("api_type") == "token"]
    if token_flows:
        print("  TOKEN ENDPOINTS:")
        for tf in token_flows:
            ti = tf.get("token_info", {})
            status = "EXTRACTED" if ti.get("token_extracted") else "NOT FOUND"
            print(f"    Step {tf['step']:3d}  {tf['request']['method']} {tf['request']['path']}"
                  f"  -> {tf['response']['status_code']}  [{status}]")
        print()

    # Experience API flow
    exp_flows = [f for f in flows if f.get("api_type") == "experience"]
    if exp_flows:
        print("  EXPERIENCE API CALLS:")
        for ef in exp_flows:
            uuid = ef.get("experience_uuid", "?")[:8]
            uses_token = ef.get("auth", {}).get("uses_captured_token", False)
            token_marker = f" [token from step {ef['auth']['token_from_step']}]" if uses_token else ""
            print(f"    Step {ef['step']:3d}  {ef['request']['method']} "
                  f".../{uuid}...  -> {ef['response']['status_code']}  "
                  f"({ef['label']}){token_marker}")
        print()

    # Other API calls
    other_flows = [f for f in flows if f.get("api_type") not in ("token", "experience")]
    if other_flows:
        print("  OTHER API CALLS:")
        for of_ in other_flows:
            uses_token = of_.get("auth", {}).get("uses_captured_token", False)
            token_marker = f" [token]" if uses_token else ""
            print(f"    Step {of_['step']:3d}  {of_['request']['method']:6s} "
                  f"{of_['request']['path'][:65]:<65s}  "
                  f"-> {of_['response']['status_code']}  "
                  f"({of_['label']}){token_marker}")
        print()

    # Full timeline
    print("  FULL TIMELINE:")
    for flow in flows:
        req = flow["request"]
        resp = flow["response"]
        status = resp.get("status_code", "???")
        api_type = flow.get("api_type", "?")
        label = flow.get("label", "unknown")
        uses_token = flow.get("auth", {}).get("uses_captured_token", False)

        markers = []
        if api_type == "token":
            markers.append("TOKEN")
        if api_type == "experience":
            markers.append("EXP")
        if uses_token:
            markers.append(f"tok:step{flow['auth']['token_from_step']}")

        marker_str = f" [{', '.join(markers)}]" if markers else ""

        has_body = " [body]" if req.get("body") else ""

        print(
            f"    {flow['step']:3d}  {req['method']:6s} "
            f"{req['path'][:60]:<60s}  "
            f"{status}  ({label}){marker_str}{has_body}"
        )

    print(f"\n{'='*70}")

    # Stats
    methods = {}
    api_types = {}
    for flow in flows:
        m = flow["request"]["method"]
        methods[m] = methods.get(m, 0) + 1
        at = flow.get("api_type", "other")
        api_types[at] = api_types.get(at, 0) + 1

    print(f"  Methods:    {', '.join(f'{m}: {c}' for m, c in sorted(methods.items()))}")
    print(f"  API types:  {', '.join(f'{t}: {c}' for t, c in sorted(api_types.items()))}")

    token_using = sum(1 for f in flows if f.get("auth", {}).get("uses_captured_token"))
    print(f"  Using auth: {token_using}/{len(flows)} calls use captured token")
    print()


def generate_journey_template(flows: list[dict]):
    JOURNEY_PATH.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# CVS Vaccine Scheduling -- User Journey & API Map",
        "",
        "This document maps each step of the vaccine scheduling user journey",
        "to the underlying API calls captured during the recording session.",
        "",
        "## Authentication Flow",
        "",
    ]

    token_flows = [f for f in flows if f.get("api_type") == "token"]
    if token_flows:
        for tf in token_flows:
            req = tf["request"]
            ti = tf.get("token_info", {})
            lines.append(f"### Step {tf['step']}: Token Acquisition")
            lines.append(f"- **Endpoint**: `{req['method']} {req['path']}`")
            lines.append(f"- **Status**: {tf['response']['status_code']}")
            lines.append(f"- **Token extracted**: {ti.get('token_extracted', False)}")
            if ti.get("token_preview"):
                lines.append(f"- **Token preview**: `{ti['token_preview']}`")
            lines.append(f"- **Purpose**: _Obtain guest auth token for subsequent API calls_")
            lines.append("")
    else:
        lines.append("_No token endpoints captured. Check capture/config.py TOKEN_ENDPOINT_PATHS._")
        lines.append("")

    lines.extend([
        "## Scheduling Journey Steps",
        "",
    ])

    # Group experience APIs by label
    exp_flows = [f for f in flows if f.get("api_type") == "experience"]
    other_flows = [f for f in flows if f.get("api_type") not in ("token", "experience")]
    journey_flows = sorted(exp_flows + other_flows, key=lambda f: f["step"])

    for flow in journey_flows:
        req = flow["request"]
        resp = flow["response"]
        label = flow.get("label", "unknown")
        api_type = flow.get("api_type", "other")

        section_title = label.replace("_", " ").title()
        lines.append(f"### Step {flow['step']}: {section_title}")
        lines.append(f"- **API type**: {api_type}")
        lines.append(f"- **Endpoint**: `{req['method']} {req['path']}`")
        lines.append(f"- **Label**: `{label}`")
        lines.append(f"- **Status**: {resp.get('status_code', '?')}")

        if flow.get("experience_uuid"):
            lines.append(f"- **Experience UUID**: `{flow['experience_uuid']}`")

        auth = flow.get("auth", {})
        if auth.get("uses_captured_token"):
            lines.append(f"- **Auth**: Uses token from step {auth['token_from_step']}")
        elif auth.get("headers"):
            headers_list = list(auth["headers"].keys())
            lines.append(f"- **Auth headers**: {', '.join(f'`{h}`' for h in headers_list)}")

        if req.get("query"):
            lines.append(f"- **Query params**: `{req['query'][:120]}`")

        if req.get("body") and isinstance(req["body"], dict):
            keys = list(req["body"].keys())[:10]
            lines.append(f"- **Request body keys**: {', '.join(f'`{k}`' for k in keys)}")

        if resp.get("body") and isinstance(resp["body"], dict):
            keys = list(resp["body"].keys())[:10]
            lines.append(f"- **Response body keys**: {', '.join(f'`{k}`' for k in keys)}")

        lines.append(f"- **User action**: _TODO: describe what the user did_")
        lines.append(f"- **UI shown**: _TODO: describe what the user saw_")
        lines.append("")

    # Summary table
    lines.extend([
        "---",
        "",
        "## API Endpoint Summary",
        "",
        "| Step | Method | Path | Label | Type | Status | Auth |",
        "|------|--------|------|-------|------|--------|------|",
    ])

    for flow in flows:
        req = flow["request"]
        resp = flow["response"]
        auth_str = "token" if flow.get("auth", {}).get("uses_captured_token") else "-"
        if flow.get("api_type") == "token":
            auth_str = "PROVIDES"
        lines.append(
            f"| {flow['step']} | {req['method']} "
            f"| `{req['path'][:55]}` "
            f"| {flow.get('label', '')} "
            f"| {flow.get('api_type', '?')} "
            f"| {resp.get('status_code', '?')} "
            f"| {auth_str} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## Token Flow Diagram",
        "",
        "```",
    ])

    if token_flows:
        lines.append(f"  Step {token_flows[0]['step']}: GET /api/guest/v1/token --> token")
        for flow in journey_flows:
            auth = flow.get("auth", {})
            if auth.get("uses_captured_token"):
                path = flow["request"]["path"]
                if len(path) > 50:
                    path = path[:47] + "..."
                lines.append(f"  Step {flow['step']}: {flow['request']['method']} {path} <-- token")

    lines.extend(["```", ""])

    with open(JOURNEY_PATH, "w") as f:
        f.write("\n".join(lines))

    print(f"  Generated {JOURNEY_PATH}")
    print("  Edit the _TODO_ placeholders to describe each user action.\n")


def main():
    flows = load_flows()

    if not flows:
        print("\n  No captured flows found in capture/raw_flows/")
        print("  Run the capture session first:")
        print("    ./capture/start_capture.sh\n")
        sys.exit(1)

    print_summary(flows)
    generate_journey_template(flows)

    if CATALOG_PATH.exists():
        with open(CATALOG_PATH) as f:
            catalog = json.load(f)
        n_endpoints = len(catalog.get("endpoints", []))
        n_uuids = len(catalog.get("experience_uuids", {}))
        n_tokens = len(catalog.get("token_endpoints", []))
        print(f"  API catalog: {CATALOG_PATH}")
        print(f"    {n_endpoints} unique endpoints, {n_uuids} experience UUIDs, {n_tokens} tokens")

    print()
    print("  Next steps:")
    print("    1. Review docs/api_catalog.json for endpoint details")
    print("    2. Edit docs/USER_JOURNEY.md to fill in user actions & UI descriptions")
    print("    3. Review individual flows in capture/raw_flows/")
    print()


if __name__ == "__main__":
    main()
