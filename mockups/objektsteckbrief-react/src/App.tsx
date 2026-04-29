import { useEffect, useState } from 'react'
import { AppShell } from './components/AppShell'
import { SteckbriefPage } from './pages/SteckbriefPage'
import { DueRadarPage } from './pages/DueRadarPage'

type Theme = 'light' | 'dark'
type Route = 'steckbrief' | 'dueradar'

function readRouteFromHash(): Route {
  const hash = window.location.hash.replace(/^#\/?/, '')
  if (hash === 'dueradar' || hash === 'due-radar' || hash === 'kanban') return 'dueradar'
  return 'steckbrief'
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = typeof window !== 'undefined' ? window.localStorage.getItem('theme') : null
    return stored === 'dark' || stored === 'light' ? stored : 'light'
  })

  const [route, setRouteState] = useState<Route>(readRouteFromHash)

  // Theme persist
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    window.localStorage.setItem('theme', theme)
  }, [theme])

  // Hash sync (deep-link friendly)
  useEffect(() => {
    const handler = () => setRouteState(readRouteFromHash())
    window.addEventListener('hashchange', handler)
    return () => window.removeEventListener('hashchange', handler)
  }, [])

  const setRoute = (r: Route) => {
    window.location.hash = `#/${r}`
    setRouteState(r)
    window.scrollTo({ top: 0 })
  }

  return (
    <AppShell route={route} setRoute={setRoute} theme={theme} setTheme={setTheme}>
      {route === 'steckbrief' && <SteckbriefPage />}
      {route === 'dueradar' && <DueRadarPage />}
    </AppShell>
  )
}
