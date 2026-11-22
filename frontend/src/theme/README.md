# Тема: что менять под клиента

Сайт — шаблон. Под нового клиента меняются **только** эти места:

| Что | Где |
|---|---|
| Название, короткое имя, описание, язык | `src/theme/theme.config.ts` → `name`, `shortName`, `description`, `lang` |
| Цвета манифеста PWA и фон иконок | `theme.config.ts` → `colors` |
| Контакты в подвале | `theme.config.ts` → `contacts` |
| Оператор персональных данных (политика) | `theme.config.ts` → `personalDataOperator` |
| Цвета, скругления, тени, шрифт, отступы | `src/theme/tokens.css` (CSS-переменные) |
| Логотип и иконки | `public/brand/` |

## Порядок действий

1. Заполнить `theme.config.ts` (название, контакты, реквизиты).
2. Подобрать цвета в `tokens.css`. Проверить:
   - `--color-header-bg` = `colors.themeColor`, `--color-bg` = `colors.backgroundColor`
     в `theme.config.ts` (CSS и манифест читаются разными механизмами, поэтому значения дублируются);
   - белый текст на `--color-accent` читается (контраст не ниже 4.5:1).
3. Заменить логотип `public/brand/logo.svg` (квадратный SVG, важное — в центре).
   Если клиент дал PNG — сделать из него квадратный SVG или положить PNG 512×512
   и поправить `images` в `pwa-assets.config.ts`.
4. Перегенерировать иконки: `npm run generate-pwa-assets`
   (создаёт `pwa-*.png`, `maskable-icon-512x512.png`, `apple-touch-icon-180x180.png`, `favicon.ico`
   в `public/brand/`; фон maskable/apple — `colors.iconBackground`).
5. `npm run build` и проверить установку PWA (см. `frontend/README.md`).

Компоненты не содержат «зашитых» цветов и названий — всё берётся из темы.
Если для клиента понадобилось поменять что-то вне перечисленных файлов,
это повод вынести настройку в тему, а не править компонент под одного клиента.
