export interface RuntimeFlags {
	mode: string;
}

interface RuntimeEnv {
	DEV?: boolean;
	MODE?: string;
}

export function resolveRuntimeFlags(env: RuntimeEnv): RuntimeFlags {
	return { mode: env.MODE ?? (env.DEV ? 'development' : 'production') };
}

export const runtimeFlags: RuntimeFlags = resolveRuntimeFlags({
	DEV: import.meta.env.DEV,
	MODE: import.meta.env.MODE,
});
