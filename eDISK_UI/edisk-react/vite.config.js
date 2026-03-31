import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig(({ mode }) => {
  const isGHPages = mode === 'ghpages';

  return {
    plugins: [react()],

    server: {
      port: 3000,
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },

    build: isGHPages
      ? {
          // ── GitHub Pages build ──
          // Output to dist/ for deployment as a standalone static site
          outDir: 'dist',
          emptyOutDir: true,
          // base must match the repo name for GH Pages routing
        }
      : {
          // ── Django-integrated build (original) ──
          // Output into Django's static folder for same-origin serving
          outDir: path.resolve(__dirname, '../ui_agent/static/react'),
          emptyOutDir: true,
          rollupOptions: {
            output: {
              entryFileNames: 'js/[name]-[hash].js',
              chunkFileNames: 'js/[name]-[hash].js',
              assetFileNames: 'assets/[name]-[hash].[ext]',
            },
          },
        },

    // For GitHub Pages, assets must be loaded from /REPO_NAME/ subpath
    base: isGHPages ? '/' : '/',
  };
});