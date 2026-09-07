import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(__dirname, '../..');

export default defineConfig({
  plugins: [react(), viteSingleFile()],
  root: __dirname,
  base: './',
  resolve: {
    alias: {
      '@': path.resolve(projectRoot, 'src'),
      'next/navigation': path.resolve(__dirname, 'next-navigation-shim.ts'),
      'next/link': path.resolve(__dirname, 'next-link-shim.tsx'),
    },
  },
  css: {
    postcss: path.resolve(projectRoot, 'postcss.config.js'),
  },
  build: {
    outDir: path.resolve(projectRoot, 'dist'),
    emptyOutDir: true,
  },
});
