import { useEffect } from 'react'
import { Outlet, useLocation } from 'react-router'
import { BottomNav } from './BottomNav'
import { Footer } from './Footer'
import { Header } from './Header'

/** Общий каркас страниц: шапка, содержимое, подвал и нижняя навигация (телефон). */
export function Layout() {
  const { pathname } = useLocation()

  // При переходе на другую страницу начинаем с верха.
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])

  return (
    <div className="layout">
      <a href="#main" className="skip-link">
        Перейти к содержимому
      </a>
      <Header />
      <main id="main" className="layout__main container">
        <Outlet />
      </main>
      <Footer />
      <BottomNav />
    </div>
  )
}
