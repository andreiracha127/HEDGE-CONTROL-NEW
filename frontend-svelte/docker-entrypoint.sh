#!/bin/sh
set -e

PORT="${PORT:-8080}"
case "$PORT" in
  ""|*[!0-9]*)
    echo "Invalid PORT: $PORT" >&2
    exit 1
    ;;
esac

sed "s/\${PORT}/$PORT/g" \
  /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf

# Generate runtime config from environment variables
# This avoids sed-injection of env vars into built JS
cat > /usr/share/nginx/html/config.json <<EOCONFIG
{
  "apiBaseUrl": "${VITE_API_BASE_URL:-http://localhost:8000}"
}
EOCONFIG

exec "$@"
