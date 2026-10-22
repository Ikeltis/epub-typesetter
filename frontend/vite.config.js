import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    // 开发时把 /api 转给后端
    proxy: { '/api': process.env.API_TARGET || 'http://localhost:8000' },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
