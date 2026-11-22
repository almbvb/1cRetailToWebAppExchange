# Фронтенд сайта доставки продуктов

Vite + React + TypeScript, SPA, PWA (`vite-plugin-pwa`), маршрутизация `react-router`.
Версии зависимостей закреплены точно (`package.json` + `package-lock.json`).

## Установка

```powershell
cd frontend
npm ci
```

## Запуск в разработке

```powershell
npm run dev                  # или из корня репозитория: .\scripts\dev_frontend.ps1
```

- http://localhost:3000 (порт фиксирован, `strictPort`: если занят — ошибка, а не другой порт).
- `/api` и `/media` проксируются на backend http://127.0.0.1:8090
  (другой адрес — переменная окружения `BACKEND_URL`).
- В подвале индикатор «Сервер доступен / недоступен» (опрос `GET /api/health`).
- Открыть с телефона в локальной сети: `npm run dev -- --host`.

## Проверки и сборка

```powershell
npm run lint        # oxlint
npm run typecheck   # tsc -b
npm run build       # проверка типов + сборка в dist/
npm run preview     # раздача dist/ на http://localhost:4173 (с тем же прокси)
```

## PWA

- Манифест, `sw.js` и `registerSW.js` создаются только при сборке; в `npm run dev` service worker выключен.
- Обновление — `autoUpdate`: новая версия подхватывается при следующем открытии.
- Кэш: статика приложения — precache; `/api/*` — только сеть (NetworkOnly), никогда не кэшируется;
  `/media/*` (картинки) — StaleWhileRevalidate, до 300 файлов на 7 дней.
- Проверка: `npm run build; npm run preview` → Chrome DevTools → Application → Manifest / Service workers,
  Lighthouse → «Progressive Web App». Установка на телефон требует HTTPS (кроме localhost).
- Иконки: исходник `public/brand/logo.svg`, PNG и `favicon.ico` — `npm run generate-pwa-assets`.

## Тема (кастомизация под клиента)

Только `src/theme/theme.config.ts`, `src/theme/tokens.css` и `public/brand/`.
Подробно — [src/theme/README.md](src/theme/README.md).

## Структура

```
src/
  api/client.ts        fetch-обёртка: JSON, таймаут, ошибки {"error":{code,message,details}} → ApiError
  components/          Layout (шапка, подвал, нижняя навигация), индикатор сервера, иконки
  pages/               страницы-заглушки: каталог, корзина, кабинет, политика, 404
  styles/              базовые стили и каркас (только CSS-переменные темы)
  theme/               тема клиента
  router.tsx           маршруты
```
