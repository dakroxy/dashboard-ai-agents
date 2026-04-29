import { ReactNode } from 'react'

type Theme = 'light' | 'dark'
type Route = 'steckbrief' | 'dueradar'

interface Props {
  route: Route
  setRoute: (r: Route) => void
  theme: Theme
  setTheme: (t: Theme) => void
  children: ReactNode
}

/**
 * Schmaler globaler Top-Bar — sitzt ueber Page-spezifischen Headern.
 * Demonstriert: in Variante B sind das die Pixel, die immer da sind
 * (kein Re-Mount, weil derselbe React-Tree).
 */
export function AppShell({ route, setRoute, theme, setTheme, children }: Props) {
  return (
    <div className="min-h-screen relative">
      <div className="sticky top-0 z-50 bg-[var(--bg)] border-b border-[var(--border-2)]">
        <div className="px-7 py-2 flex items-center gap-6">
          {/* Brand */}
          <a href="#/steckbrief" className="flex items-center gap-2.5 group">
            <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-[var(--accent)]">DBS</span>
            <span className="w-px h-3 bg-[var(--border-2)]" />
            <span className="font-display italic text-sm text-[var(--text-1)] group-hover:text-[var(--accent)] transition-colors">
              KI-Plattform
            </span>
          </a>

          {/* Module nav */}
          <nav className="flex items-stretch border border-[var(--border)] bg-[var(--surface-1)] ml-2">
            <ModuleTab active={route === 'steckbrief'} onClick={() => setRoute('steckbrief')}>
              Objektsteckbrief
              <span className="ml-2 text-[9px] font-mono text-[var(--text-3)]">HAM61</span>
            </ModuleTab>
            <ModuleTab active={route === 'dueradar'} onClick={() => setRoute('dueradar')}>
              Due-Radar
              <span className="ml-2 text-[9px] font-mono text-[var(--danger)]">3 fällig</span>
            </ModuleTab>
            <ModuleTab disabled>Versicherer-Registry</ModuleTab>
            <ModuleTab disabled>SEPA-Workflow</ModuleTab>
            <ModuleTab disabled>Mietverwaltung</ModuleTab>
          </nav>

          <div className="ml-auto flex items-center gap-3">
            {/* Cmd-K hint — illustration only in B */}
            <button className="flex items-center gap-2 px-2.5 py-1 border border-[var(--border)] bg-[var(--surface-1)] text-[10px] font-mono uppercase tracking-wider text-[var(--text-3)] hover:text-[var(--text-1)] hover:border-[var(--border-2)] transition-colors">
              <SearchSvg />
              Suche
              <span className="kbd">⌘K</span>
            </button>

            {/* Theme switch */}
            <div className="flex items-stretch border border-[var(--border)] bg-[var(--surface-1)]">
              {(['light', 'dark'] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTheme(t)}
                  className={`px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] font-mono transition-colors border-r border-[var(--border)] last:border-r-0 ${
                    theme === t
                      ? 'bg-[var(--surface-3)] text-[var(--text-1)]'
                      : 'text-[var(--text-3)] hover:text-[var(--text-1)] hover:bg-[var(--surface-2)]'
                  }`}
                  title={t === 'light' ? 'Hanseatic Paper' : 'Hanseatic Terminal'}
                >
                  {t === 'light' ? '☀' : '☾'}
                </button>
              ))}
            </div>

            {/* User chip */}
            <div className="flex items-center gap-2 px-2 py-1 border border-[var(--border)] bg-[var(--surface-1)]">
              <span className="inline-flex items-center justify-center w-5 h-5 bg-[var(--accent-bg)] border border-[var(--accent-line)] font-mono text-[10px] font-medium text-[var(--accent)]">DK</span>
              <span className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-2)]">kroll@dbshome.de</span>
            </div>
          </div>
        </div>
      </div>

      {children}
    </div>
  )
}

function ModuleTab({ children, active, disabled, onClick }: {
  children: ReactNode; active?: boolean; disabled?: boolean; onClick?: () => void
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`px-3 py-1.5 text-[10px] uppercase tracking-[0.16em] font-mono transition-colors border-r border-[var(--border)] last:border-r-0 ${
        active
          ? 'bg-[var(--accent)] text-[var(--bg)]'
          : disabled
            ? 'text-[var(--text-4)] cursor-not-allowed'
            : 'text-[var(--text-2)] hover:text-[var(--text-1)] hover:bg-[var(--surface-2)]'
      }`}
    >
      {children}
    </button>
  )
}

function SearchSvg() {
  return (
    <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4">
      <circle cx="5" cy="5" r="3.5" />
      <path d="M7.5 7.5 L10.5 10.5" strokeLinecap="round" />
    </svg>
  )
}
