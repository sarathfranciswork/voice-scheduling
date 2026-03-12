#!/usr/bin/env bash
#
# Launch mitmproxy web UI with the CVS capture addon.
#
# Usage:
#   ./capture/start_capture.sh          # Web UI (recommended)
#   ./capture/start_capture.sh --cli    # Terminal UI
#   ./capture/start_capture.sh --dump   # Headless (log only)
#
# After starting, configure your browser to use HTTP proxy at localhost:8080
# or launch a browser with:
#   google-chrome --proxy-server="http://localhost:8080" --ignore-certificate-errors

set -euo pipefail
cd "$(dirname "$0")/.."

# Clean previous capture if desired
if [[ "${1:-}" == "--clean" ]]; then
    echo "Cleaning previous capture data..."
    rm -rf capture/raw_flows/*
    rm -f docs/api_catalog.json
    shift
fi

MODE="${1:-}"

echo "=============================================="
echo "  CVS Vaccine Scheduling API Capture"
echo "=============================================="
echo ""
echo "  Proxy address:  http://localhost:8080"
echo "  CA cert:        ~/.mitmproxy/mitmproxy-ca-cert.pem"
echo ""
echo "  Configure your browser to use the proxy, then"
echo "  navigate to the CVS scheduling page:"
echo "    https://www.cvs.com/vaccine/intake/store/cvd-schedule"
echo ""
echo "  Or launch Chrome with proxy:"
echo "    google-chrome --proxy-server='http://localhost:8080'"
echo ""
echo "=============================================="
echo ""

if [[ "$MODE" == "--cli" ]]; then
    exec mitmproxy --scripts capture/mitmproxy_addon.py
elif [[ "$MODE" == "--dump" ]]; then
    exec mitmdump --scripts capture/mitmproxy_addon.py
else
    exec mitmweb --scripts capture/mitmproxy_addon.py
fi
