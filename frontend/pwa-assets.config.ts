// Генерация PNG-иконок PWA из SVG-исходника: npm run generate-pwa-assets
// Результат кладётся рядом с исходником, в public/brand/:
//   pwa-64x64.png, pwa-192x192.png, pwa-512x512.png, maskable-icon-512x512.png,
//   apple-touch-icon-180x180.png, favicon.ico
import { defineConfig, minimal2023Preset } from '@vite-pwa/assets-generator/config'
import { theme } from './src/theme/theme.config.ts'

export default defineConfig({
  headLinkOptions: { preset: '2023' },
  preset: {
    ...minimal2023Preset,
    // У maskable- и apple-иконок нет прозрачности: заливаем фирменным цветом,
    // логотип уменьшаем, чтобы он целиком попал в «безопасную зону».
    maskable: {
      ...minimal2023Preset.maskable,
      padding: 0.3,
      resizeOptions: { background: theme.colors.iconBackground },
    },
    apple: {
      ...minimal2023Preset.apple,
      padding: 0.3,
      resizeOptions: { background: theme.colors.iconBackground },
    },
  },
  images: ['public/brand/logo.svg'],
})
