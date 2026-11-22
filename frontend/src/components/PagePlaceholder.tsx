import type { ReactNode } from 'react'

interface PagePlaceholderProps {
  title: string
  text: ReactNode
  icon?: ReactNode
  children?: ReactNode
}

/** Карточка-заглушка для страниц, которые появятся на следующих этапах. */
export function PagePlaceholder({ title, text, icon, children }: PagePlaceholderProps) {
  return (
    <section className="placeholder card">
      {icon && <div className="placeholder__icon">{icon}</div>}
      <h1 className="placeholder__title">{title}</h1>
      <p className="placeholder__text">{text}</p>
      {children}
    </section>
  )
}
