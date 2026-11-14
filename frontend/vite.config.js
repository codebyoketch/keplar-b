import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const proxy = {
    '/api': {
      target: env.CAIRN_API_TARGET || 'http://127.0.0.1:8000',
      changeOrigin: true,
    },
  };

  return {
    server: { proxy },
    preview: { proxy },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
    },
  };
});
