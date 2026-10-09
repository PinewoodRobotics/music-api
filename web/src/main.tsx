import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

async function start() {
  const params = new URLSearchParams(location.search)
  if (import.meta.env.DEV && (params.has('mock') || sessionStorage.getItem('mock'))) {
    const { installMock } = await import('./dev/mock')
    installMock(params.get('mock'))
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

void start()
