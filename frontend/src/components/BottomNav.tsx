import { NavLink } from 'react-router'
import { CartIcon, CatalogIcon, UserIcon } from './icons'

const items = [
  { to: '/', label: 'Каталог', Icon: CatalogIcon, end: true },
  { to: '/cart', label: 'Корзина', Icon: CartIcon, end: false },
  { to: '/account', label: 'Кабинет', Icon: UserIcon, end: false },
]

/** Нижняя навигация — только на телефоне (на широких экранах скрыта стилями). */
export function BottomNav() {
  return (
    <nav className="bottom-nav" aria-label="Основная навигация">
      {items.map(({ to, label, Icon, end }) => (
        <NavLink key={to} to={to} end={end} className="bottom-nav__item">
          <Icon />
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  )
}
