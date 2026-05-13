// @vitest-environment node
// @ts-nocheck — Node-only filesystem-scan test; runs under tsx/Vitest. The
//                @types/node package is not a project dep, so svelte-check
//                cannot resolve node:fs / node:path / process. Type-check
//                is intentionally skipped for this file.
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { STALE_PATH_LITERALS } from './paths';

// Vitest runs with frontend-svelte as cwd; resolve src/ from there.
const SRC_ROOT = resolve(process.cwd(), 'src');

// Files that legitimately mention stale literals (the path module itself,
// the drift guard test, and the schema typedef may all contain related
// substrings). Every other file under src/ must be free of them.
// Files that legitimately mention stale literals (the path module exposes
// the literal list for the drift guard itself; the schema typedef contains
// adjacent canonical strings that may overlap). Test files are excluded
// from the scan up-front because they may quote stale literals as assertion
// strings.
const ALLOWLIST = new Set<string>([
	'lib/api/paths.ts',
	'lib/api/schema.d.ts',
]);

const SCANNED_EXTENSIONS = new Set(['.ts', '.svelte', '.svelte.ts', '.js']);

function isTestFile(name: string): boolean {
	return /\.test\.(ts|js)$/i.test(name) || /\.svelte\.test\.ts$/i.test(name);
}

function listFiles(dir: string, acc: string[]) {
	for (const entry of readdirSync(dir)) {
		const full = join(dir, entry);
		const s = statSync(full);
		if (s.isDirectory()) {
			if (entry === 'node_modules' || entry === '.svelte-kit' || entry === 'dist') continue;
			if (entry === 'tests') continue;
			listFiles(full, acc);
			continue;
		}
		if (!s.isFile()) continue;
		// Tests may quote stale literals in assertions; production-code paths
		// are what the guard polices.
		if (isTestFile(entry)) continue;
		if (SCANNED_EXTENSIONS.has(extension(entry))) acc.push(full);
	}
}

function extension(name: string): string {
	if (name.endsWith('.svelte.ts')) return '.svelte.ts';
	const idx = name.lastIndexOf('.');
	return idx < 0 ? '' : name.slice(idx).toLowerCase();
}

describe('frontend-svelte path drift guard', () => {
	it('rejects every stale path literal under src/ outside the allowlist', () => {
		const files: string[] = [];
		listFiles(SRC_ROOT, files);

		const offenders: Array<{ file: string; literal: string; line: number }> = [];

		for (const file of files) {
			const rel = relative(SRC_ROOT, file).split(/[\\/]/).join('/');
			if (ALLOWLIST.has(rel)) continue;

			const content = readFileSync(file, 'utf8');
			const lines = content.split(/\r?\n/);
			for (let i = 0; i < lines.length; i++) {
				for (const literal of STALE_PATH_LITERALS) {
					if (lines[i].includes(literal)) {
						offenders.push({ file: rel, literal, line: i + 1 });
					}
				}
			}
		}

		if (offenders.length > 0) {
			const report = offenders
				.map((o) => `  ${o.file}:${o.line} — '${o.literal}'`)
				.join('\n');
			throw new Error(
				`Stale path literals reappeared under frontend-svelte/src:\n${report}\n` +
					`Use the typed helpers in src/lib/api/paths.ts.`,
			);
		}

		expect(offenders).toEqual([]);
	});

	it('confirms the allowlist references existing files (avoids decay)', () => {
		for (const rel of ALLOWLIST) {
			const path = join(SRC_ROOT, rel);
			expect(() => statSync(path), `allowlist entry ${rel} should exist`).not.toThrow();
		}
	});
});
