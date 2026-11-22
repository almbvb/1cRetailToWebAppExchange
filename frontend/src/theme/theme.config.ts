/**
 * Конфигурация темы — ЕДИНСТВЕННОЕ место (вместе с tokens.css и public/brand/),
 * которое меняется под конкретного клиента.
 *
 * Файл читается и приложением (шапка, подвал, страницы), и сборкой
 * (vite.config.ts: манифест PWA, <title>, meta для iOS; pwa-assets.config.ts: фон иконок).
 * Поэтому здесь только чистые данные — без импортов из React/Vite и без обращения к DOM.
 */

export interface ThemeConfig {
  /** Полное название магазина: заголовок вкладки, манифест (name), шапка. */
  name: string
  /** Короткое имя для значка на экране телефона (до 12 символов). */
  shortName: string
  /** Описание для манифеста и meta description. */
  description: string
  /** Язык интерфейса (манифест, <html lang>). */
  lang: string
  /** Цвета для манифеста и meta theme-color. Должны совпадать с tokens.css. */
  colors: {
    /** Цвет строки состояния / заголовка окна PWA (= --color-header-bg). */
    themeColor: string
    /** Фон заставки при запуске PWA (= --color-bg). */
    backgroundColor: string
    /** Фон под maskable- и apple-иконками (обычно фирменный цвет логотипа). */
    iconBackground: string
  }
  /** Пути к файлам бренда в public/brand/ (от корня сайта). */
  brand: {
    logo: string
  }
  /** Контакты магазина (показываются в подвале). */
  contacts: {
    phone: string
    email: string
    address: string
    workingHours: string
  }
  /** Оператор персональных данных (152-ФЗ) — для политики конфиденциальности. */
  personalDataOperator: {
    legalName: string
    inn: string
    ogrn: string
    legalAddress: string
    email: string
  }
}

export const theme: ThemeConfig = {
  name: 'Продукты рядом',
  shortName: 'Продукты',
  description: 'Доставка свежих продуктов к вашей двери',
  lang: 'ru',
  colors: {
    themeColor: '#eaf6ec',
    backgroundColor: '#f7fbf6',
    iconBackground: '#3f9e5a',
  },
  brand: {
    logo: '/brand/logo.svg',
  },
  contacts: {
    phone: '+7 (000) 000-00-00',
    email: 'info@example.com',
    address: 'г. Город, ул. Примерная, д. 1',
    workingHours: 'Ежедневно с 8:00 до 22:00',
  },
  personalDataOperator: {
    legalName: 'ООО «Пример»',
    inn: '0000000000',
    ogrn: '0000000000000',
    legalAddress: 'г. Город, ул. Примерная, д. 1',
    email: 'privacy@example.com',
  },
}
