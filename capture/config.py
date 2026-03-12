"""
Configurable URL patterns for the mitmproxy capture addon.

Edit these lists to adjust what gets captured vs. filtered during the
CVS vaccine scheduling API recording session.
"""

# ---------------------------------------------------------------------------
# EXCLUDE patterns -- requests matching ANY of these are silently dropped.
# Checked against the full URL (scheme + host + path + query).
# ---------------------------------------------------------------------------

EXCLUDE_DOMAIN_KEYWORDS = [
    # Analytics & tracking
    "google-analytics", "googletagmanager", "analytics", "doubleclick",
    "googlesyndication", "googleadservices", "google.com/pagead",
    "facebook.net", "facebook.com/tr", "fbcdn",
    "optimizely", "adobedtm", "demdex", "omtrdc", "2o7.net",
    "hotjar", "fullstory", "mouseflow", "crazyegg", "luckyorange",
    "amplitude", "mixpanel", "segment.io", "segment.com",
    "branch.io", "appsflyer", "adjust.com",
    "taboola", "outbrain", "criteo", "adsrvr",
    # Error tracking / monitoring
    "sentry.io", "bugsnag", "newrelic", "datadoghq", "nr-data.net",
    "rollbar.com", "logrocket",
    # Fonts
    "fonts.googleapis.com", "fonts.gstatic.com", "use.typekit.net",
    # Social widgets
    "platform.twitter.com", "connect.facebook.net", "apis.google.com/js",
    # Consent / privacy managers
    "onetrust", "cookielaw", "quantcast", "truste", "evidon",
    "trustarc", "cookiebot", "osano",
    # CDN that only serves static assets
    "cloudflare.com/cdn-cgi",
    # Misc third party
    "recaptcha", "gstatic.com",
]

EXCLUDE_PATH_SUFFIXES = [
    # Static assets
    ".js", ".css", ".map",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".avif",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp4", ".webm", ".mp3",
    ".pdf",
    # Source maps
    ".js.map", ".css.map",
]

EXCLUDE_PATH_KEYWORDS = [
    "/favicon", "/manifest.json", "/robots.txt", "/sitemap",
    "/sw.js", "/service-worker",
    "/_next/static/", "/static/js/", "/static/css/", "/static/media/",
    "/webpack", "/chunk",
]

# Also exclude HTTP methods that are not interesting
EXCLUDE_METHODS = ["OPTIONS"]

# ---------------------------------------------------------------------------
# INCLUDE patterns -- if a request passes the exclude filter, it must match
# at least ONE include pattern to be captured. This ensures we only record
# CVS scheduling-related API calls.
#
# Checked against the full URL.
# ---------------------------------------------------------------------------

INCLUDE_DOMAIN_KEYWORDS = [
    "cvs.com",
]

# ---------------------------------------------------------------------------
# HIGH-PRIORITY paths -- these are ALWAYS captured if the domain matches,
# regardless of method or content type. These are the known CVS scheduling
# API prefixes.
# ---------------------------------------------------------------------------

INCLUDE_PATH_HIGH_PRIORITY = [
    "/scheduling/client/experience/",  # Experience APIs (UUID-based steps)
    "/api/guest/v1/token",             # Guest auth token endpoint
    "/api/guest/",                     # Other guest API endpoints
]

INCLUDE_PATH_KEYWORDS = [
    "/immunization", "/api/", "/scheduler/", "/store/", "/patient/",
    "/vaccine/", "/appointment/", "/availability/", "/location/",
    "/search", "/book", "/cancel", "/confirm", "/eligib",
    "/intake/", "/session/", "/auth/", "/scheduling/",
    "/experience/", "/token",
]

# Also auto-include any POST/PUT/PATCH to cvs.com regardless of path
INCLUDE_METHODS_ALWAYS = ["POST", "PUT", "PATCH", "DELETE"]

# Only capture responses with these content types (for non-high-priority paths)
INCLUDE_CONTENT_TYPES = [
    "application/json",
    "application/javascript",  # some APIs serve JSONP
    "text/json",
    "text/plain",  # sometimes JSON is served as text/plain
]

# ---------------------------------------------------------------------------
# OUTPUT settings
# ---------------------------------------------------------------------------

RAW_FLOWS_DIR = "capture/raw_flows"
API_CATALOG_PATH = "docs/api_catalog.json"

# Headers to sanitize (values replaced with "[REDACTED]")
SANITIZE_HEADERS = [
    "cookie", "set-cookie",
]

# Auth-related headers to capture separately in the "auth" section of each
# flow record (values are preserved, NOT sanitized, so we can track token flow)
AUTH_HEADERS = [
    "authorization", "x-csrf-token", "x-api-key",
    "x-session-id", "x-auth-token", "x-access-token",
]

# ---------------------------------------------------------------------------
# TOKEN TRACKING
# ---------------------------------------------------------------------------

# URL path prefix that provides auth tokens -- the addon will track the
# token value from these responses and link it to subsequent API calls.
TOKEN_ENDPOINT_PATHS = [
    "/api/guest/v1/token",
]

# Response JSON keys to look for the token value in token endpoint responses.
# The addon tries each key path in order until one is found.
TOKEN_RESPONSE_KEYS = [
    ["access_token"],
    ["token"],
    ["data", "access_token"],
    ["data", "token"],
]
