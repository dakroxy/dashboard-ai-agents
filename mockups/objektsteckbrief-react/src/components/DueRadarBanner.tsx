import { dueRadar } from '../data/mock'

export function DueRadarBanner() {
  return (
    <div className="sticky top-[193px] z-30 border-y border-[var(--warn-line)] bg-gradient-to-r from-[var(--warn-bg)] via-transparent to-[var(--danger-bg)] backdrop-blur">
      <div className="px-7 py-2 flex items-center gap-6 overflow-x-auto">
        <div className="flex items-center gap-2 shrink-0">
          <RadarIcon />
          <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-[var(--warn)]">Due-Radar · 90 d</span>
        </div>

        <div className="flex items-center gap-px shrink-0">
          {dueRadar.map((d, i) => (
            <div
              key={i}
              className="flex items-center gap-2.5 px-3 py-1 border-r border-[var(--hairline)] last:border-r-0"
            >
              <span
                className="w-1 h-3 inline-block"
                style={{ background: d.kind === 'overdue' ? 'var(--danger)' : 'var(--warn)' }}
              />
              <span className="text-xs text-[var(--text-1)] whitespace-nowrap">{d.label}</span>
              <span
                className="font-mono text-xs tabular whitespace-nowrap"
                style={{ color: d.kind === 'overdue' ? 'var(--danger)' : 'var(--warn)' }}
              >
                {d.kind === 'overdue' ? `+${d.since}d` : `${d.in}d`}
              </span>
              <span className="text-[10px] text-[var(--text-3)] whitespace-nowrap hidden xl:inline">{d.unit}</span>
            </div>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-3 text-[10px] font-mono uppercase tracking-wider text-[var(--text-3)] shrink-0">
          <span>1 überfällig · 2 in 90 d</span>
          <a href="#versicherungen" className="text-[var(--accent)] hover:underline">Sektion ▸</a>
          <a href="#" className="text-[var(--text-2)] hover:text-[var(--accent)] hover:underline">Globaler Due-Radar ▸</a>
        </div>
      </div>
    </div>
  )
}

function RadarIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 14 14" fill="none" stroke="var(--warn)" strokeWidth="1.2">
      <circle cx="7" cy="7" r="6" opacity="0.5" />
      <circle cx="7" cy="7" r="3.5" opacity="0.7" />
      <circle cx="7" cy="7" r="1" fill="var(--warn)" />
      <line x1="7" y1="7" x2="11.5" y2="3" strokeLinecap="round" />
    </svg>
  )
}
