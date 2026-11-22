import { createBrowserRouter } from 'react-router'
import { Layout } from './components/Layout'
import AccountPage from './pages/AccountPage'
import CartPage from './pages/CartPage'
import CatalogPage from './pages/CatalogPage'
import NotFoundPage from './pages/NotFoundPage'
import PrivacyPage from './pages/PrivacyPage'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <CatalogPage /> },
      { path: 'cart', element: <CartPage /> },
      { path: 'account', element: <AccountPage /> },
      { path: 'privacy', element: <PrivacyPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
