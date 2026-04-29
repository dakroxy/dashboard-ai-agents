import { IdChip, PflegegradRing } from './ui'
import { objekt } from '../data/mock'

type View = 'voll' | 'kompakt' | 'risiko'

interface Props {
  view: View
  setView: (v: View) => void
  drawerOpen: boolean
  setDrawerOpen: (b: boolean) => void
}

export function Header({ view, setView, drawerOpen, setDrawerOpen }: Props) {
  return (
    <header className="sticky top-[37px] z-40 bg-[var(--bg)]/92 backdrop-blur-md border-b border-[var(--border)]">
      {/* Top breadcrumb strip */}
      <div className="px-7 pt-3 pb-2 flex items-center gap-3 text-[10px] font-mono uppercase tracking-[0.18em] text-[var(--text-3)] border-b border-[var(--hairline)]">
        <span>DBS · Objektregister</span>
        <span className="text-[var(--text-4)]">/</span>
        <span>{objekt.district}</span>
        <span className="text-[var(--text-4)]">/</span>
        <span className="text-[var(--text-2)]">{objekt.shortCode}</span>
        <div className="ml-auto flex items-center gap-3">
          <span className="text-[var(--text-4)]">Letzter Sync</span>
          <span className="text-[var(--text-2)]">heute, 02:31</span>
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--live)] live-dot" />
        </div>
      </div>

      {/* Identity + score row */}
      <div className="px-7 pt-5 pb-4 flex items-start justify-between gap-10">
        {/* Left — identity */}
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-5 flex-wrap">
            <span
              className="font-mono text-[44px] leading-none font-medium text-[var(--accent)] tracking-tight"
              style={{ textShadow: '0 0 24px rgba(227,168,96,0.18)' }}
            >
              {objekt.shortCode}
            </span>
            <h1
              className="font-display text-[26px] leading-[1.1] font-light text-[var(--text-1)]"
              style={{ fontVariationSettings: '"opsz" 60, "SOFT" 30' }}
            >
              <span className="italic">{objekt.name}</span>
            </h1>
            <span className="text-sm text-[var(--text-2)]">{objekt.city}</span>
          </div>
          <div className="flex items-center gap-2 mt-3.5 flex-wrap">
            <IdChip label="Impower" value={objekt.impowerId} />
            <IdChip label="Facilioo" value={objekt.facilioId} />
            <IdChip label="WEG-Nr" value={objekt.wegNumberIntern} />
            <span className="ml-2 text-[11px] font-mono text-[var(--text-3)] tabular">
              {objekt.unitCount} WE · {objekt.buildings} Häuser · Bj {objekt.yearBuilt}
            </span>
          </div>
        </div>

        {/* Right — KPIs */}
        <div className="flex items-stretch gap-5 shrink-0">
          {/* Review queue panel */}
          <button
            onClick={() => setDrawerOpen(!drawerOpen)}
            className="group flex flex-col items-end justify-between border border-[var(--accent-line)] bg-[var(--accent-bg)] px-3.5 py-2.5 hover:bg-[var(--accent-bg)] hover:border-[var(--accent)] transition-colors text-left min-w-[180px]"
          >
            <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-[0.18em] text-[var(--accent)]">
              <SparkSvg />
              KI-Vorschläge
            </div>
            <div className="flex items-baseline gap-2 mt-1">
              <span className="font-mono text-[28px] font-medium text-[var(--text-1)] leading-none tabular">{objekt.reviewQueueCount}</span>
              <span className="text-xs text-[var(--text-2)]">offen</span>
            </div>
            <div className="text-[10px] text-[var(--text-3)] mt-1 group-hover:text-[var(--accent)] transition-colors">
              {drawerOpen ? 'Drawer schließen ▸' : 'Review-Queue öffnen ▸'}
            </div>
          </button>

          {/* Pflegegrad ring */}
          <div className="flex flex-col items-center gap-1.5">
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-[var(--text-3)]">Pflegegrad</div>
            <PflegegradRing score={objekt.pflegegrad} trend={objekt.pflegegradDelta} size={92} />
          </div>
        </div>
      </div>

      {/* Bottom toolbar */}
      <div className="px-7 py-2.5 flex items-center justify-between gap-6 border-t border-[var(--hairline)] bg-[var(--surface-1)]/40">
        {/* Search */}
        <div className="flex items-center gap-2 flex-1 max-w-md border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 hover:border-[var(--border-2)] transition-colors focus-within:border-[var(--accent)]">
          <SearchSvg />
          <input
            type="text"
            placeholder="Felder, Personen, Dokumente in HAM61 …"
            className="bg-transparent text-xs placeholder:text-[var(--text-3)] outline-none flex-1 text-[var(--text-1)]"
          />
          <span className="kbd">⌘K</span>
        </div>

        {/* View tabs */}
        <div className="flex items-stretch border border-[var(--border)] bg-[var(--bg)]">
          {(['voll', 'kompakt', 'risiko'] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`px-3 py-1.5 text-[10px] uppercase tracking-[0.16em] font-mono transition-colors border-r border-[var(--border)] last:border-r-0 ${
                view === v
                  ? 'bg-[var(--accent)] text-[var(--bg)] font-medium'
                  : 'text-[var(--text-2)] hover:text-[var(--text-1)] hover:bg-[var(--surface-3)]'
              }`}
            >
              {v === 'voll' ? 'Vollansicht' : v === 'kompakt' ? 'Kompakt' : 'Risiko-Fokus'}
            </button>
          ))}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1.5">
          <button className="btn">Export PDF</button>
          <button className="btn">Snapshot</button>
          <button className="btn btn-primary">An KI-Chat ▸</button>
        </div>
      </div>
    </header>
  )
}

function SearchSvg() {
  return (
    <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="var(--text-3)" strokeWidth="1.4">
      <circle cx="5" cy="5" r="3.5" />
      <path d="M7.5 7.5 L10.5 10.5" strokeLinecap="round" />
    </svg>
  )
}

function SparkSvg() {
  return (
    <svg width="9" height="9" viewBox="0 0 10 10" fill="var(--accent)">
      <path d="M5 0 L6 4 L10 5 L6 6 L5 10 L4 6 L0 5 L4 4 Z" />
    </svg>
  )
}
