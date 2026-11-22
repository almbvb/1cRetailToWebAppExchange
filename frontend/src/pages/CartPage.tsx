import { Link } from 'react-router'
import { PagePlaceholder } from '../components/PagePlaceholder'
import { CartIcon } from '../components/icons'

export default function CartPage() {
  return (
    <PagePlaceholder
      icon={<CartIcon width={40} height={40} />}
      title="Корзина"
      text="Корзина пока пуста. Оформление заказа появится на следующих этапах."
    >
      <Link to="/" className="button">
        Перейти в каталог
      </Link>
    </PagePlaceholder>
  )
}
