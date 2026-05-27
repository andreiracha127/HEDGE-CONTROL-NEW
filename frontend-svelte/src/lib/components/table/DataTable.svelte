<script lang="ts" generics="TData">
	import {
		type ColumnDef,
		type RowData,
		type Header,
		type Cell,
		getCoreRowModel,
		getSortedRowModel,
		getFilteredRowModel,
		getGroupedRowModel,
		getExpandedRowModel,
	} from '@tanstack/table-core';
	import { createSvelteTable } from './create-table.svelte';

	type Props = {
		data: TData[];
		columns: ColumnDef<TData, any>[];
		enableSorting?: boolean;
		enableGrouping?: boolean;
		isLoading?: boolean;
		emptyMessage?: string;
		rowClass?: (row: any) => string;
	};

	let {
		data,
		columns,
		enableSorting = true,
		enableGrouping = false,
		isLoading = false,
		emptyMessage = 'Nenhum dado encontrado',
		rowClass = () => '',
	}: Props = $props();

	const table = createSvelteTable<TData>(() => ({
		data,
		columns,
		getCoreRowModel: getCoreRowModel(),
		...(enableSorting ? { getSortedRowModel: getSortedRowModel() } : {}),
		...(enableGrouping
			? {
					getGroupedRowModel: getGroupedRowModel(),
					getExpandedRowModel: getExpandedRowModel(),
				}
			: {}),
		getFilteredRowModel: getFilteredRowModel(),
		columnResizeMode: 'onEnd' as const,
	}));

	/**
	 * Render a cell or header value.
	 * Column defs in this project use string-returning cell functions,
	 * so we call the function and return its result or fall back to getValue().
	 */
	function renderHeader(header: Header<TData, unknown>): string {
		const def = header.column.columnDef.header;
		if (typeof def === 'string') return def;
		if (typeof def === 'function') return String(def(header.getContext()) ?? '');
		return '';
	}

	function renderCell(cell: Cell<TData, unknown>): string {
		const def = cell.column.columnDef.cell;
		if (typeof def === 'function') return String(def(cell.getContext()) ?? '');
		const val = cell.getValue();
		return val != null ? String(val) : '';
	}
</script>

<div class="overflow-x-auto rounded border border-gray-200">
	<table class="w-full text-sm">
		<thead class="sticky top-0 z-10">
			{#each table.getHeaderGroups() as headerGroup}
				<tr class="border-b border-gray-200 bg-white text-left text-xs text-gray-500">
					{#each headerGroup.headers as header}
						<th
							class="px-3 py-2 font-medium {header.column.getCanSort() ? 'cursor-pointer select-none hover:text-gray-700' : ''}"
							style="width: {header.getSize()}px"
							onclick={header.column.getToggleSortingHandler()}
						>
							{#if !header.isPlaceholder}
								{renderHeader(header)}
								{#if header.column.getIsSorted() === 'asc'}
									<span class="ml-1">↑</span>
								{:else if header.column.getIsSorted() === 'desc'}
									<span class="ml-1">↓</span>
								{/if}
							{/if}
						</th>
					{/each}
				</tr>
			{/each}
		</thead>
		<tbody>
			{#if isLoading}
				{#each Array(5) as _}
					<tr class="border-b border-gray-200">
						{#each columns as _col}
							<td class="px-3 py-2">
								<div class="h-4 w-24 animate-pulse rounded bg-gray-100"></div>
							</td>
						{/each}
					</tr>
				{/each}
			{:else}
				{#each table.getRowModel().rows as row (row.id)}
					<tr class="border-b border-gray-200 hover:bg-gray-100 transition-colors {rowClass(row)}">
						{#each row.getVisibleCells() as cell}
							<td class="px-3 py-2">
								{#if cell.getIsGrouped()}
									<button
										onclick={row.getToggleExpandedHandler()}
										class="flex items-center gap-1 font-medium text-gray-900"
									>
										<span>{row.getIsExpanded() ? '▾' : '▸'}</span>
										<span>{renderCell(cell)}</span>
										<span class="ml-1 text-xs text-gray-500">({row.subRows.length})</span>
									</button>
								{:else if cell.getIsAggregated()}
									<span class="font-medium text-gray-700">{renderCell(cell)}</span>
								{:else if cell.getIsPlaceholder()}
									<!-- grouped placeholder -->
								{:else}
									{renderCell(cell)}
								{/if}
							</td>
						{/each}
					</tr>
				{:else}
					<tr>
						<td colspan={columns.length} class="px-3 py-8 text-center text-gray-500">
							{emptyMessage}
						</td>
					</tr>
				{/each}
			{/if}
		</tbody>
	</table>
</div>
