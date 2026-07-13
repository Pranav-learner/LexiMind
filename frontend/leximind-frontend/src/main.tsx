import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import './styles/workspace.css'
import './styles/document.css'
import './styles/viewer.css'
import './styles/chat.css'
import './styles/summary.css'
import './styles/notes.css'
import './styles/flashcards.css'
import './styles/citations.css'
import './styles/dashboard.css'
import './styles/ingestion.css'
import './styles/search.css'
import './styles/context.css'
import './styles/mmworkspace.css'
import './styles/collaboration.css'
import './styles/security.css'
import App from './App.tsx'
import { AuthProvider } from './context/AuthContext'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
