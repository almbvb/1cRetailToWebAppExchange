import { theme } from '../theme/theme.config'

/** Политика обработки персональных данных — заглушка, текст утверждает клиент. */
export default function PrivacyPage() {
  const op = theme.personalDataOperator

  return (
    <article className="card prose">
      <h1>Политика конфиденциальности</h1>
      <p className="muted">
        Это заглушка. Полный текст политики обработки персональных данных будет добавлен позже.
      </p>

      <h2>Оператор персональных данных</h2>
      <dl className="details-list">
        <dt>Наименование</dt>
        <dd>{op.legalName}</dd>
        <dt>ИНН</dt>
        <dd>{op.inn}</dd>
        <dt>ОГРН</dt>
        <dd>{op.ogrn}</dd>
        <dt>Адрес</dt>
        <dd>{op.legalAddress}</dd>
        <dt>Эл. почта для обращений</dt>
        <dd>
          <a href={`mailto:${op.email}`}>{op.email}</a>
        </dd>
      </dl>
    </article>
  )
}
