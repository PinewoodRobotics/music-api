import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type ProxyOptions } from 'vite'

const target = 'https://music-api.pinewoodrobotics.org'

function proxy(): ProxyOptions {
  return {
    target,
    changeOrigin: true,
    secure: true,
    configure(server) {
      server.on('proxyReq', (req) => {
        const token = process.env.MUSIC_API_TOKEN
        if (token && !req.getHeader('authorization')) req.setHeader('Authorization', `Bearer ${token}`)
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/',
  build: { outDir: 'dist', assetsDir: 'assets' },
  server: { proxy: { '/api': proxy(), '/auth': proxy() } },
})
