import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const cloudApiProxy = {
  target: 'http://170.106.137.89',
  changeOrigin: true,
}

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': cloudApiProxy,
    },
  },
  preview: {
    proxy: {
      '/api': cloudApiProxy,
    },
  },
})
