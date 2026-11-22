import { Link } from 'react-router'
import { PagePlaceholder } from '../components/PagePlaceholder'

export default function NotFoundPage() {
  return (
    <PagePlaceholder title="Страница не найдена" text="Такой страницы нет. Возможно, ссылка устарела.">
      <Link to="/" className="button">
        На главную
      </Link>
    </PagePlaceholder>
  )
}
