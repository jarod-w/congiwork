import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@cogniwork/shared-ui': '../../packages/shared-ui/src/index.ts',
      '@cogniwork/shared-types': '../../packages/shared-types/src/index.ts',
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
});
