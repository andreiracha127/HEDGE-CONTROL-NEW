#!/bin/sh
set -eu

PORT="${PORT:-8080}"
case "$PORT" in
  ""|*[!0-9]*)
    echo "Invalid PORT: $PORT" >&2
    exit 1
    ;;
esac

# Export safe defaults for all CSP template vars before envsubst / derivation
# (prevents set -u abort and empty connect-src / Report-To when container started
# without explicit VITE_API_BASE_URL or CLERK_FAPI_HOST).
export VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://localhost:8000}"

# Derive CLERK_FAPI_HOST from VITE_CLERK_PUBLISHABLE_KEY if not explicitly set.
# Clerk publishable keys are url-safe base64 of "<fapi-host>$" — strip prefix,
# add base64 padding, decode, strip trailing dollar sign.
if [ -z "${CLERK_FAPI_HOST:-}" ]; then
  if [ -z "${VITE_CLERK_PUBLISHABLE_KEY:-}" ]; then
    echo "FATAL: neither CLERK_FAPI_HOST nor VITE_CLERK_PUBLISHABLE_KEY is set" >&2
    exit 1
  fi
  # Strip pk_test_ / pk_live_ prefix
  _key_body="${VITE_CLERK_PUBLISHABLE_KEY#pk_test_}"
  _key_body="${_key_body#pk_live_}"
  # Pad to multiple of 4 with '='
  case $(( ${#_key_body} % 4 )) in
    2) _key_body="${_key_body}==" ;;
    3) _key_body="${_key_body}=" ;;
  esac
  # Decode (busybox base64 in alpine accepts -d). Strip trailing $ and any whitespace.
  CLERK_FAPI_HOST=$(printf '%s' "$_key_body" | base64 -d 2>/dev/null | sed -e 's/\$$//' -e 's/[[:space:]]//g')
  if [ -z "$CLERK_FAPI_HOST" ] || ! printf '%s' "$CLERK_FAPI_HOST" | grep -qE '^[a-z0-9.-]+\.[a-z]+$'; then
    echo "FATAL: failed to derive CLERK_FAPI_HOST from VITE_CLERK_PUBLISHABLE_KEY" >&2
    exit 1
  fi
fi
export CLERK_FAPI_HOST

# Derive WebSocket base URL from HTTP API base URL for CSP connect-src
# (https://... -> wss://..., http://... -> ws://...)
export VITE_WS_BASE_URL="${VITE_WS_BASE_URL:-$(printf '%s' "$VITE_API_BASE_URL" | sed -e 's#^https://#wss://#' -e 's#^http://#ws://#')}"

# Substitute all templated variables (PORT for listen, plus CSP Report-Only vars)
# at container start so nginx.conf lands with concrete origins (no literal ${...})
envsubst '${PORT} ${CLERK_FAPI_HOST} ${VITE_API_BASE_URL} ${VITE_WS_BASE_URL}' \
  < /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf

# Generate runtime config from environment variables
# This avoids build-time injection of env vars into built JS
cat > /usr/share/nginx/html/config.json <<EOCONFIG
{
  "apiBaseUrl": "${VITE_API_BASE_URL:-http://localhost:8000}"
}
EOCONFIG

exec "$@"
