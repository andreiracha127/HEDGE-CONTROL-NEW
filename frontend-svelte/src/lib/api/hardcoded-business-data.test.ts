import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = process.cwd();
const SCANNED_DIRS = ['src/routes/(protected)', 'src/lib/components/alcast', 'src/lib/alcast'];

const BUSINESS_DATA_PATTERNS: Array<[RegExp, string]> = [
	[/\b(?:RFQ|ORD|APR|CT|EXP)-2026-\d{4,6}\b/, 'prototype business identifier'],
	[/\b(?:M\. Santos|R\. Almeida|A\. Costa|L\. Ferreira|Maria Santos)\b/, 'prototype person name'],
	[/\b(?:Refinitiv|Bloomberg|B3 \(FX\)|CME Group)\b/, 'hardcoded market-data provider'],
	[/\b(?:09:14|09:12|09:04|09:08|09:18|09:19|09:34|11:30 BST)\b/, 'hardcoded operational timestamp'],
	[/\b(?:2\.645,50|2\.632,15|2\.635,00|5\.124|5,1240|84\.200|122\.840|204\.165|312\.880|412\.500|158\.310)\b/, 'hardcoded financial literal'],
	[/\b(?:36\.300|17\.900|18\.400|49,3|24,1 M|3,2 M)\b/, 'hardcoded KPI literal'],
	[/\b(?:sampleQuotes|const\s+feed\s*=|const\s+providers\s*=|const\s+forward\s*=|const\s+sliders\s*=|const\s+historical\s*=|const\s+docs\s*=)\b/, 'prototype static business array'],
	[/\b(?:midFor|vs Mid LME|Refinitiv ao vivo|atualizado\s+(?:às\s+)?09:14|snapshot 27\/05\/2026)\b/, 'prototype market or snapshot fallback'],
];

function filesUnder(dir: string): string[] {
	const fullDir = join(ROOT, dir);
	return readdirSync(fullDir).flatMap((entry) => {
		const full = join(fullDir, entry);
		if (statSync(full).isDirectory()) return filesUnder(relative(ROOT, full));
		return (full.endsWith('.svelte') || full.endsWith('.ts')) && !full.endsWith('.test.ts') ? [full] : [];
	});
}

describe('hardcoded business data scanner', () => {
	it('keeps protected production routes free of prototype financial and operational data', () => {
		const offenders = SCANNED_DIRS.flatMap(filesUnder).flatMap((file) => {
			const source = readFileSync(file, 'utf8');
			return BUSINESS_DATA_PATTERNS.flatMap(([pattern, reason]) => {
				const match = source.match(pattern);
				return match ? [`${relative(ROOT, file)}: ${reason}: ${match[0]}`] : [];
			});
		});

		expect(offenders).toEqual([]);
	});
});
