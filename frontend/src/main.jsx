import React from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext.jsx'
import App from './App.jsx'
import ProtectedRoute from './components/ProtectedRoute.jsx'
import { RoleGate } from './components/RoleGate.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import Navbar from './components/Navbar.jsx'
import Login from './pages/Login.jsx'
import Register from './pages/Register.jsx'
import Dashboard from './pages/Dashboard.jsx'
import POS from './pages/POS.jsx'
import Inventory from './pages/Inventory.jsx'
import Sales from './pages/Sales.jsx'
import Customers from './pages/Customers.jsx'
import Staff from './pages/Staff.jsx'
import Chat from './pages/Chat.jsx'
import Profile from './pages/Profile.jsx'
import './styles.css'

const router = createBrowserRouter([
  {
    path: '/login',
    element: (
      <ErrorBoundary>
        <Login />
      </ErrorBoundary>
    ),
  },
  {
    path: '/register',
    element: (
      <ErrorBoundary>
        <Register />
      </ErrorBoundary>
    ),
  },
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <ErrorBoundary>
          <App />
        </ErrorBoundary>
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'pos', element: <POS /> },
      { path: 'inventory', element: <Inventory /> },
      { path: 'sales', element: <Sales /> },
      { path: 'customers', element: <Customers /> },
      { path: 'chat', element: <Chat /> },
      { path: 'profile', element: <Profile /> },
      {
        path: 'staff',
        element: (
          <RoleGate allowedRoles={['owner']} fallback={<p className="muted">Owners only.</p>}>
            <Staff />
          </RoleGate>
        ),
      },
    ],
  },
  { path: '*', element: <NotFound /> },
])

function NotFound() {
  return (
    <div style={{ padding: '2rem', textAlign: 'center' }}>
      <h1>404</h1>
      <p className="muted">Page not found.</p>
    </div>
  )
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  </React.StrictMode>,
)
