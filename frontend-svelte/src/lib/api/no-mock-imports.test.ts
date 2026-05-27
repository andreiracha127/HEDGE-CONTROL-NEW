import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, test } from 'vitest';

const ROOT = process.cwd();
const SCANNED_DIRS = ['src/routes', 'src/lib/components'];
const MOCK_IMPORT = /import\s+[^;]*from\s+['"]\$lib\/alcast\/mock['"]/;

function filesUnder(dir: string): string[] {
	const fullDir = join(ROOT, dir);
	const entries = readdirSync(fullDir);
	return entries.flatMap((entry) => {
		const full = join(fullDir, entry);
		if (statSync(full).isDirectory()) return filesUnder(relative(ROOT, full));
		return full.endsWith('.svelte') || full.endsWith('.ts') ? [full] : [];
	});
}

describe('production code mock imports', () => {
	test('does not import the Alcast mock dataset from routes or components', () => {
		const offenders = SCANNED_DIRS.flatMap(filesUnder).filter((file) =>
			MOCK_IMPORT.test(readFileSync(file, 'utf8')),
		);

		expect(offenders.map((file) => relative(ROOT, file))).toEqual([]);
	});
});

