#!/usr/bin/env bash
# Checks if schema.d.ts is in sync with the backend OpenAPI spec.
# Requires backend to be running at $API_BASE_URL (default: http://localhost:8000)
set -euo pipefail

API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"
SCHEMA_FILE="src/lib/api/schema.d.ts"
TMP_SPEC="/tmp/openapi-schema-check.json"
TMP_FILE="/tmp/schema-check.d.ts"

if [ ! -f "$SCHEMA_FILE" ]; then
  echo "ERROR: $SCHEMA_FILE not found. Run 'npm run api:types' first."
  exit 1
fi

echo "Fetching OpenAPI spec from ${API_BASE_URL}/openapi.json ..."
curl -fsS "${API_BASE_URL}/openapi.json" | node -e '
const fs = require("fs");

function sortObject(value) {
  if (Array.isArray(value)) {
    return value.map(sortObject);
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, sortObject(value[key])])
    );
  }
  return value;
}

const spec = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(sortObject(spec)));
' > "$TMP_SPEC"
npx openapi-typescript "$TMP_SPEC" -o "$TMP_FILE"

if diff -q "$SCHEMA_FILE" "$TMP_FILE" > /dev/null 2>&1; then
  echo "OK: schema.d.ts is in sync with backend."
  rm -f "$TMP_SPEC" "$TMP_FILE"
  exit 0
else
  echo "DRIFT DETECTED: schema.d.ts is out of sync with backend."
  echo ""
  echo "Diff (current vs generated):"
  diff --unified "$SCHEMA_FILE" "$TMP_FILE" || true
  echo ""
  echo "Run 'npm run api:types' to regenerate."
  rm -f "$TMP_SPEC" "$TMP_FILE"
  exit 1
fi
