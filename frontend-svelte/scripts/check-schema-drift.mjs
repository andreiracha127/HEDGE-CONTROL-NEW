#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";
import { execFileSync } from "node:child_process";

const out = path.join(tmpdir(), `schema-check-${process.pid}-${Date.now()}.d.ts`);

try {
	execFileSync(process.execPath, ["scripts/regen-schema.mjs", out], {
		stdio: "inherit",
		env: process.env,
	});
	const current = fs.readFileSync("src/lib/api/schema.d.ts", "utf8");
	const generated = fs.readFileSync(out, "utf8");
	if (current !== generated) {
		console.error("src/lib/api/schema.d.ts differs from regenerated OpenAPI types");
		process.exitCode = 1;
	}
} finally {
	if (fs.existsSync(out)) {
		fs.unlinkSync(out);
	}
}
