import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import './index.css'
import App from './routes.jsx'
import { AuthProvider } from './hooks/use-auth.jsx'

/**
 * The route table in `routes.jsx` is the application.
 *
 * This entry point used to mount `App.jsx`, a standalone prototype that talked
 * to `/trace` with its own hard-coded markup and its own inline stylesheet. It
 * is still on disk and still builds; it is simply not what the browser runs.
 * `routes.jsx` owns the public pages, the access guard and the `/app` shell, so
 * that is what gets mounted here.
 *
 * `AuthProvider` is mounted here because nothing else mounts it: it is exported
 * from `hooks/use-auth.jsx` and read by `useAuth` in the route guard, the app
 * shell, the sidebar and every page that needs to know the deployment's access
 * mode, but no file in the tree ever wrapped the app in it. It sits outside
 * `BrowserRouter` because it holds no router state of its own — it reads
 * `localStorage` and `/auth/status` — so it cannot care which is inside.
 */
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AuthProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </AuthProvider>
  </StrictMode>,
)
