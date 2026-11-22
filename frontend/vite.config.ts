import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'
import { theme } from './src/theme/theme.config.ts'

// Адрес backend (FastAPI). Можно переопределить: $env:BACKEND_URL = 'http://127.0.0.1:8091'
const backendUrl = process.env.BACKEND_URL ?? 'http://127.0.0.1:8090'

// Host не подменяем: backend видит адрес dev-сервера и строит ссылки на него.
const backendProxy = {
  '/api': { target: backendUrl },
  '/media': { target: backendUrl },
}

/** Подставляет значения темы в index.html: %THEME_NAME%, %THEME_SHORT_NAME% и т. д. */
function themeHtml(): Plugin {
  const escapeHtml = (s: string) =>
    s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const values: Record<string, string> = {
    THEME_NAME: theme.name,
    THEME_SHORT_NAME: theme.shortName,
    THEME_DESCRIPTION: theme.description,
    THEME_LANG: theme.lang,
    THEME_COLOR: theme.colors.themeColor,
  }
  return {
    name: 'theme-html',
    transformIndexHtml(html) {
      return html.replace(/%(THEME_[A-Z_]+)%/g, (match, key: string) =>
        key in values ? escapeHtml(values[key]) : match,
      )
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    themeHtml(),
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      // Файлы из public/, которые не попадают в манифест, но нужны офлайн.
      includeAssets: ['brand/logo.svg', 'brand/favicon.ico', 'brand/apple-touch-icon-180x180.png'],
      manifest: {
        id: '/',
        name: theme.name,
        short_name: theme.shortName,
        description: theme.description,
        lang: theme.lang,
        theme_color: theme.colors.themeColor,
        background_color: theme.colors.backgroundColor,
        display: 'standalone',
        start_url: '/',
        scope: '/',
        icons: [
          { src: '/brand/pwa-64x64.png', sizes: '64x64', type: 'image/png' },
          { src: '/brand/pwa-192x192.png', sizes: '192x192', type: 'image/png' },
          { src: '/brand/pwa-512x512.png', sizes: '512x512', type: 'image/png' },
          {
            src: '/brand/maskable-icon-512x512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        // Статика приложения кэшируется при установке service worker.
        globPatterns: ['**/*.{js,css,html,svg,png,ico,webmanifest,woff2}'],
        cleanupOutdatedCaches: true,
        // SPA: переходы по страницам отдаём из index.html, но не для API и медиа.
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/media\//],
        runtimeCaching: [
          {
            // Данные API никогда не кэшируются service worker'ом — только сеть.
            urlPattern: ({ url }) => url.pathname.startsWith('/api/'),
            handler: 'NetworkOnly',
          },
          {
            // Картинки товаров: показываем из кэша, в фоне обновляем.
            urlPattern: ({ url }) => url.pathname.startsWith('/media/'),
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'media',
              expiration: { maxEntries: 300, maxAgeSeconds: 7 * 24 * 60 * 60 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
      // В режиме разработки service worker выключен, чтобы не мешал HMR.
      devOptions: { enabled: false },
    }),
  ],
  server: {
    port: 3000,
    strictPort: true,
    proxy: backendProxy,
  },
  preview: {
    port: 4173,
    strictPort: true,
    proxy: backendProxy,
  },
})
