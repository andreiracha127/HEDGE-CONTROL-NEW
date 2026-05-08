#!/usr/bin/env node
// Regenerate src/lib/api/schema.d.ts from the backend's OpenAPI spec,
// applying the same recursive alphabetical key sort that
// scripts/check-schema-drift.sh runs in CI. Without the sort step, the
// generated file would preserve FastAPI's route-registration order and
// drift against the CI reference even when no schema actually changed.
//
// Source resolution:
//   $OPENAPI_SOURCE — file path or http(s) URL (default
//                     http://localhost:8000/openapi.json, requires the
//                     backend to be running)
// Output path:
//   first CLI arg, default src/lib/api/schema.d.ts
import fs from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";
import { execSync } from "node:child_process";

const SOURCE = process.env.OPENAPI_SOURCE || "http://localhost:8000/openapi.json";
const OUT = process.argv[2] || "src/lib/api/schema.d.ts";

function sortObject(value) {
	if (Array.isArray(value)) return value.map(sortObject);
	if (value && typeof value === "object") {
		return Object.fromEntries(
			Object.keys(value)
				.sort()
				.map((k) => [k, sortObject(value[k])]),
		);
	}
	return value;
}

const isUrl = /^https?:\/\//i.test(SOURCE);
const spec = isUrl
	? await fetch(SOURCE).then((r) => {
			if (!r.ok) throw new Error(`fetch ${SOURCE} → ${r.status}`);
			return r.json();
		})
	: JSON.parse(fs.readFileSync(SOURCE, "utf8"));

const tmp = path.join(tmpdir(), `openapi-sorted-${process.pid}-${Date.now()}.json`);
fs.writeFileSync(tmp, JSON.stringify(sortObject(spec)));
try {
	execSync(`npx openapi-typescript "${tmp}" -o "${OUT}"`, { stdio: "inherit" });
} finally {
	fs.unlinkSync(tmp);
}
