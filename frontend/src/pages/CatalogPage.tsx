import { PagePlaceholder } from '../components/PagePlaceholder'
import { CatalogIcon } from '../components/icons'

export default function CatalogPage() {
  return (
    <PagePlaceholder
      icon={<CatalogIcon width={40} height={40} />}
      title="Каталог"
      text="Скоро здесь будет каталог товаров."
    />
  )
}
