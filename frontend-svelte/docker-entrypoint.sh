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
export CLERK_FAPI_HOST="${CLERK_FAPI_HOST:-clerk.accounts.dev}"

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
