import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5181,
    proxy: {
      '/ws': {
        target: 'ws://localhost:5180',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
