import { Link } from 'react-router'
import { theme } from '../theme/theme.config'
import { ServerStatus } from './ServerStatus'

// Год вычисляем один раз при загрузке, а не при каждом рендере.
const currentYear = new Date().getFullYear()

export function Footer() {
  const { contacts } = theme
  const phoneHref = `tel:${contacts.phone.replace(/[^\d+]/g, '')}`

  return (
    <footer className="footer">
      <div className="footer__inner container">
        <div className="footer__contacts">
          <strong>{theme.name}</strong>
          <a href={phoneHref}>{contacts.phone}</a>
          <a href={`mailto:${contacts.email}`}>{contacts.email}</a>
          <span>{contacts.address}</span>
          <span>{contacts.workingHours}</span>
        </div>
        <div className="footer__meta">
          <Link to="/privacy">Политика конфиденциальности</Link>
          <span>
            © {currentYear} {theme.name}
          </span>
          <ServerStatus />
        </div>
      </div>
    </footer>
  )
}
