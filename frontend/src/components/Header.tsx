import { Link, NavLink } from 'react-router'
import { theme } from '../theme/theme.config'
import { CartIcon, LoginIcon } from './icons'

/** Шапка: логотип с названием и быстрые ссылки (пока заглушки). */
export function Header() {
  return (
    <header className="header">
      <div className="header__inner container">
        <Link to="/" className="header__brand" aria-label={`${theme.name} — на главную`}>
          <img src={theme.brand.logo} alt="" width="36" height="36" className="header__logo" />
          <span className="header__name">{theme.name}</span>
        </Link>

        <nav className="header__actions" aria-label="Быстрые ссылки">
          <NavLink to="/cart" className="icon-link">
            <CartIcon />
            <span className="icon-link__label">Корзина</span>
          </NavLink>
          <NavLink to="/account" className="icon-link">
            <LoginIcon />
            <span className="icon-link__label">Вход</span>
          </NavLink>
        </nav>
      </div>
    </header>
  )
}
