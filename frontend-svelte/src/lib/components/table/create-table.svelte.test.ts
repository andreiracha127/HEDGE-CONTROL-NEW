import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import TableTestWrapper from '../../../tests/helpers/TableTestWrapper.svelte';
import {
	getCoreRowModel,
	getSortedRowModel,
	getFilteredRowModel,
	type ColumnDef,
	type Table,
} from '@tanstack/table-core';

interface TestData {
	id: number;
	name: string;
	value: number;
}

const testData: TestData[] = [
	{ id: 1, name: 'Alpha', value: 30 },
	{ id: 2, name: 'Beta', value: 10 },
	{ id: 3, name: 'Gamma', value: 20 },
];

const columns: ColumnDef<TestData, unknown>[] = [
	{ accessorFn: (row) => row.id, id: 'id', header: 'ID' },
	{ accessorFn: (row) => row.name, id: 'name', header: 'Name' },
	{ accessorFn: (row) => row.value, id: 'value', header: 'Value' },
];

function renderTable(opts: Partial<{
	data: TestData[];
	sorting: Array<{ id: string; desc: boolean }>;
	enableSorting: boolean;
	globalFilter: string;
	columnVisibility: Record<string, boolean>;
	pagination: { pageIndex: number; pageSize: number };
}> = {}): Table<TestData> {
	let capturedTable: Table<TestData>;

	const data = opts.data ?? testData;
	const state: Record<string, unknown> = {};
	if (opts.sorting) state.sorting = opts.sorting;
	if (opts.globalFilter !== undefined) state.globalFilter = opts.globalFilter;
	if (opts.columnVisibility) state.columnVisibility = opts.columnVisibility;
	if (opts.pagination) state.pagination = opts.pagination;

	render(TableTestWrapper, {
		props: {
			options: () => ({
				data,
				columns,
				getCoreRowModel: getCoreRowModel(),
				...(opts.sorting || opts.enableSorting ? { getSortedRowModel: getSortedRowModel() } : {}),
				...(opts.globalFilter !== undefined ? { getFilteredRowModel: getFilteredRowModel() } : {}),
				...(Object.keys(state).length > 0 ? { state } : {}),
			}),
			onTable: (t: Table<TestData>) => { capturedTable = t; },
		},
	});

	return capturedTable!;
}

describe('createSvelteTable', () => {
	it('creates a table with data and columns', () => {
		const table = renderTable();
		expect(table).toBeDefined();
		expect(table.getRowModel().rows).toHaveLength(3);
	});

	it('returns correct cell values', () => {
		const table = renderTable();
		const firstRow = table.getRowModel().rows[0];
		expect(firstRow.getValue('id')).toBe(1);
		expect(firstRow.getValue('name')).toBe('Alpha');
		expect(firstRow.getValue('value')).toBe(30);
	});

	it('renders row elements in DOM', () => {
		renderTable();
		const rows = screen.getAllByTestId('row');
		expect(rows).toHaveLength(3);
	});

	it('supports sorting', () => {
		const table = renderTable({ sorting: [{ id: 'value', desc: false }] });
		const rows = table.getSortedRowModel().rows;
		const values = rows.map((r) => r.getValue('value'));
		expect(values).toEqual([10, 20, 30]);
	});

	it('supports descending sort', () => {
		const table = renderTable({ sorting: [{ id: 'value', desc: true }] });
		const rows = table.getSortedRowModel().rows;
		const values = rows.map((r) => r.getValue('value'));
		expect(values).toEqual([30, 20, 10]);
	});

	it('syncs internally managed sorting state', async () => {
		const table = renderTable({ enableSorting: true });
		table.setSorting([{ id: 'value', desc: false }]);
		await tick();
		expect(table.getState().sorting).toEqual([{ id: 'value', desc: false }]);
	});

	it('supports global filtering', () => {
		const table = renderTable({ globalFilter: 'Beta' });
		const rows = table.getFilteredRowModel().rows;
		expect(rows).toHaveLength(1);
		expect(rows[0].getValue('name')).toBe('Beta');
	});

	it('handles empty data', () => {
		const table = renderTable({ data: [] });
		expect(table.getRowModel().rows).toHaveLength(0);
	});

	it('exposes column definitions', () => {
		const table = renderTable();
		const allColumns = table.getAllColumns();
		expect(allColumns).toHaveLength(3);
		expect(allColumns.map((c) => c.id)).toEqual(['id', 'name', 'value']);
	});

	it('supports column visibility', () => {
		const table = renderTable({ columnVisibility: { value: false } });
		const visibleIds = table.getVisibleLeafColumns().map((c) => c.id);
		expect(visibleIds).toEqual(['id', 'name']);
	});

	it('supports pagination state', () => {
		const manyRows = Array.from({ length: 25 }, (_, i) => ({
			id: i,
			name: `Row ${i}`,
			value: i * 10,
		}));
		const table = renderTable({ data: manyRows, pagination: { pageIndex: 0, pageSize: 10 } });
		expect(table.getPageCount()).toBe(3);
	});
});
