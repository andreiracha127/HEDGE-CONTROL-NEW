/**
 * TanStack Table Svelte 5 adapter.
 *
 * Uses $state for table options and state, $effect for syncing.
 * Based on: https://github.com/walker-tx/svelte5-tanstack-table-reference
 */

import {
	createTable,
	type RowData,
	type TableOptions,
	type TableState,
	type Table,
	type TableOptionsResolved,
} from '@tanstack/table-core';

export function createSvelteTable<TData extends RowData>(
	optionsFn: () => TableOptions<TData>
): Table<TData> {
	const resolvedOptions = $derived(optionsFn());

	let tableState = $state<TableState>({} as TableState);

	function handleStateChange(updater: ((prev: TableState) => TableState) | TableState) {
		tableState = typeof updater === 'function' ? updater(tableState) : updater;
	}

	const initialOptions = optionsFn();
	const table = createTable({
		...initialOptions,
		state: initialOptions.state ?? {},
		onStateChange: handleStateChange,
		renderFallbackValue: null,
	} as TableOptionsResolved<TData>);

	$effect(() => {
		table.setOptions((prev) => ({
			...prev,
			...resolvedOptions,
			state: { ...(tableState as TableState), ...resolvedOptions.state },
			onStateChange: handleStateChange,
		}));
	});

	return table;
}
