import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	build: {
		rollupOptions: {
			output: {
				manualChunks(id) {
					if (id.includes('zrender')) return 'zrender';
					if (id.includes('echarts')) return 'echarts';
					if (id.includes('@tanstack/table-core')) return 'tanstack-table';
				}
			}
		}
	}
});
