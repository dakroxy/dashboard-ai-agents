import { ProvenanceIcon } from './ui'
import { technik } from '../data/mock'

const START = 1920
const END = 2030

interface Event {
  year: number
  label: string
  kind: 'origin' | 'major' | 'minor' | 'planned'
}

export function HistorieTimeline() {
  const events: Event[] = technik.history
  const today = 2026

  // Group events by year so co-located ticks stack labels
  const byYear: Record<number, Event[]> = {}
  events.forEach(e => {
    (byYear[e.year] = byYear[e.year] || []).push(e)
  })

  const W = 1240
  const H = 240
  const PAD = { top: 50, right: 30, bottom: 60, left: 30 }
  const innerW = W - PAD.left - PAD.right

  const xFor = (y: number) => PAD.left + ((y - START) / (END - START)) * innerW
  const axisY = PAD.top + (H - PAD.top - PAD.bottom) / 2

  const decades: number[] = []
  for (let y = START; y <= END; y += 10) decades.push(y)

  const colorFor = (k: Event['kind']) => ({
    origin: 'var(--accent)',
    major: 'var(--text-1)',
    minor: 'var(--text-2)',
    planned: 'var(--warn)',
  })[k]

  return (
    <div className="frame-card p-6 mt-6">
      <header className="flex items-end justify-between mb-2">
        <div>
          <div className="section-eyebrow mb-1">Bauakte · Sanierungsverlauf</div>
          <h3 className="font-display text-[20px] italic font-light text-[var(--text-1)]">
            102 Jahre, sieben Eingriffe — und einer für 2026 vorgesehen.
          </h3>
        </div>
        <div className="flex items-center gap-4 text-[10px] font-mono uppercase tracking-wider text-[var(--text-3)]">
          <span>5 manuell · 2 KI ✦ · 1 geplant</span>
        </div>
      </header>

      <div className="relative -mx-2 overflow-x-auto overflow-y-hidden">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMinYMid meet" className="block w-full h-auto" style={{ minWidth: 800 }}>
          {/* defs: vertical hatching for "today" half */}
          <defs>
            <pattern id="hatch" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="6" stroke="var(--hairline)" strokeWidth="1" />
            </pattern>
            <linearGradient id="axisFade" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="var(--border)" stopOpacity="0.2" />
              <stop offset="10%" stopColor="var(--border)" stopOpacity="1" />
              <stop offset="90%" stopColor="var(--border)" stopOpacity="1" />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.4" />
            </linearGradient>
          </defs>

          {/* Future zone hatch */}
          <rect
            x={xFor(today)} y={PAD.top - 20}
            width={W - PAD.right - xFor(today)} height={H - PAD.top - PAD.bottom + 40}
            fill="url(#hatch)" opacity="0.6"
          />

          {/* Main axis */}
          <line
            x1={PAD.left} y1={axisY}
            x2={W - PAD.right} y2={axisY}
            stroke="url(#axisFade)" strokeWidth="1.5"
          />

          {/* Decade ticks */}
          {decades.map(y => {
            const x = xFor(y)
            const isMajor = y % 50 === 0
            return (
              <g key={y}>
                <line
                  x1={x} y1={axisY - (isMajor ? 7 : 4)}
                  x2={x} y2={axisY + (isMajor ? 7 : 4)}
                  stroke={isMajor ? 'var(--text-3)' : 'var(--border-2)'}
                  strokeWidth={isMajor ? 1.2 : 0.8}
                />
                <text
                  x={x} y={axisY + 22}
                  fill={isMajor ? 'var(--text-2)' : 'var(--text-4)'}
                  fontSize={isMajor ? 11 : 9}
                  fontFamily="IBM Plex Mono"
                  textAnchor="middle"
                  letterSpacing="0.05em"
                >
                  {y}
                </text>
              </g>
            )
          })}

          {/* Today marker */}
          <g>
            <line
              x1={xFor(today)} y1={PAD.top - 12}
              x2={xFor(today)} y2={H - PAD.bottom + 4}
              stroke="var(--accent)" strokeWidth="0.8" strokeDasharray="3 3"
            />
            <text
              x={xFor(today) + 6} y={PAD.top - 4}
              fill="var(--accent)" fontSize="9" fontFamily="IBM Plex Mono"
              letterSpacing="0.18em"
            >
              HEUTE · 28.04.2026
            </text>
          </g>

          {/* Events */}
          {Object.entries(byYear).map(([yearStr, evts]) => {
            const year = parseInt(yearStr)
            const x = xFor(year)
            const primary = evts[0]
            const isOrigin = primary.kind === 'origin'
            const isMajor = primary.kind === 'major'
            const isPlanned = primary.kind === 'planned'
            const stroke = colorFor(primary.kind)
            const above = year % 4 === 0 || isOrigin // alternate above/below for readability
            const labelY = above ? axisY - 22 : axisY + 42

            // For multi-event years, stack vertically away from axis
            return (
              <g key={year}>
                {/* Vertical drop */}
                <line
                  x1={x} y1={axisY - (isOrigin || isMajor ? 18 : 12)}
                  x2={x} y2={axisY + (isOrigin || isMajor ? 18 : 12)}
                  stroke={stroke}
                  strokeWidth={isOrigin || isMajor ? 1.5 : 1}
                  strokeDasharray={isPlanned ? '2 2' : undefined}
                />

                {/* Marker */}
                <circle
                  cx={x} cy={axisY}
                  r={isOrigin ? 6 : isMajor ? 5 : 4}
                  fill={isOrigin ? stroke : 'var(--bg)'}
                  stroke={stroke}
                  strokeWidth={isOrigin ? 1.5 : isMajor ? 2 : 1.5}
                />
                {isOrigin && (
                  <circle cx={x} cy={axisY} r={10} fill="none" stroke={stroke} strokeWidth="0.6" opacity="0.5" />
                )}

                {/* Year on opposite side */}
                <text
                  x={x} y={above ? axisY + 38 : axisY - 28}
                  fill={isOrigin ? stroke : isPlanned ? 'var(--warn)' : 'var(--text-2)'}
                  fontSize={isOrigin || isMajor ? 13 : 11}
                  fontWeight={isOrigin || isMajor ? 600 : 400}
                  fontFamily="IBM Plex Mono"
                  textAnchor="middle"
                  letterSpacing="0.04em"
                >
                  {year}
                </text>

                {/* Event labels stacked */}
                {evts.map((e, i) => (
                  <g key={i}>
                    <text
                      x={x}
                      y={above ? labelY - i * 14 : labelY + i * 14}
                      fill={isOrigin ? 'var(--accent)' : isPlanned ? 'var(--warn)' : i === 0 ? 'var(--text-1)' : 'var(--text-2)'}
                      fontSize={i === 0 && (isOrigin || isMajor) ? 12 : 10.5}
                      fontFamily={i === 0 && isOrigin ? 'Fraunces' : 'IBM Plex Sans'}
                      fontStyle={i === 0 && isOrigin ? 'italic' : 'normal'}
                      fontWeight={i === 0 ? 500 : 400}
                      textAnchor="middle"
                      letterSpacing={i === 0 && isOrigin ? '0.02em' : '0'}
                    >
                      {e.label}
                    </text>
                  </g>
                ))}

                {/* AI sparkle marker on Heizung 2014 + Fenster 2014 */}
                {year === 2014 && (
                  <g transform={`translate(${x + 18}, ${axisY - 14})`}>
                    <path d="M0 -3 L1 0 L4 1 L1 2 L0 5 L-1 2 L-4 1 L-1 0 Z" fill="var(--accent)" />
                  </g>
                )}
              </g>
            )
          })}

          {/* Footer scale */}
          <text x={PAD.left} y={H - 14} fill="var(--text-4)" fontSize="9" fontFamily="IBM Plex Mono" letterSpacing="0.15em">
            VOR 102 JAHREN
          </text>
          <text x={W - PAD.right} y={H - 14} fill="var(--text-4)" fontSize="9" fontFamily="IBM Plex Mono" letterSpacing="0.15em" textAnchor="end">
            +4 JAHRE GEPLANT
          </text>
        </svg>
      </div>

      {/* Legend bar */}
      <div className="mt-3 pt-3 border-t border-[var(--hairline)] flex items-center justify-between gap-6">
        <div className="flex items-center gap-5 text-[10px] font-mono uppercase tracking-wider text-[var(--text-3)]">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 rounded-full bg-[var(--accent)]" />
            Errichtung
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 rounded-full bg-[var(--bg)] border-2 border-[var(--text-1)]" />
            Gesamt­sanierung
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-[var(--bg)] border-[1.5px] border-[var(--text-2)]" />
            Komponente
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-[var(--bg)] border-[1.5px] border-[var(--warn)] border-dashed" />
            Geplant / Beschluss
          </span>
        </div>
        <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-wider text-[var(--text-3)]">
          <ProvenanceIcon kind="ai" />
          <span>Heizung-Bj. 2014 — KI-Vorschlag aus Wartungsprotokoll</span>
        </div>
      </div>
    </div>
  )
}
