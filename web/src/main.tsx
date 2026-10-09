import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

async function start() {
  if (import.meta.env.DEV && new URLSearchParams(location.search).has('mock')) {
    const { installMock } = await import('./dev/mock')
    installMock(new URLSearchParams(location.search).get('mock'))
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

void start()
