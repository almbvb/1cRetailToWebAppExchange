import { PagePlaceholder } from '../components/PagePlaceholder'
import { UserIcon } from '../components/icons'

export default function AccountPage() {
  return (
    <PagePlaceholder
      icon={<UserIcon width={40} height={40} />}
      title="Личный кабинет"
      text="Вход, история заказов и адреса доставки появятся на следующих этапах."
    />
  )
}
