import { ReactNode } from 'react'
import type { Provenance } from '../data/mock'

/* ─────────────────────────────────────────────────────
   Provenance — tiny glyph next to every data field
   manual = filled square  ·  mirror = sync glyph
   ai     = sparkle        ·  derived = sigma
   missing = hollow circle
   ───────────────────────────────────────────────────── */
export function ProvenanceIcon({ kind, size = 9 }: { kind: Provenance; size?: number }) {
  const titles: Record<Provenance, string> = {
    manual: 'Manuell gepflegt',
    mirror: 'Impower-Spiegel',
    ai: 'KI-Vorschlag offen',
    derived: 'Berechnet',
    missing: 'Feld leer',
  }
  const colors: Record<Provenance, string> = {
    manual: 'var(--text-2)',
    mirror: 'var(--info)',
    ai: 'var(--accent)',
    derived: 'var(--text-3)',
    missing: 'var(--text-4)',
  }
  const c = colors[kind]
  return (
    <span title={titles[kind]} className="inline-flex items-center justify-center align-middle" style={{ width: size + 4, height: size + 4 }}>
      <svg width={size} height={size} viewBox="0 0 10 10" style={{ display: 'block' }}>
        {kind === 'manual' && <rect x="1.5" y="1.5" width="7" height="7" fill={c} />}
        {kind === 'mirror' && (
          <g fill="none" stroke={c} strokeWidth="1.2" strokeLinecap="square">
            <path d="M2 3.5 H7 L5.5 2 M8 6.5 H3 L4.5 8" />
          </g>
        )}
        {kind === 'ai' && (
          <path d="M5 1 L6 4 L9 5 L6 6 L5 9 L4 6 L1 5 L4 4 Z" fill={c} />
        )}
        {kind === 'derived' && (
          <text x="5" y="8" fontSize="9" fontFamily="IBM Plex Mono" fontWeight="600" textAnchor="middle" fill={c}>Σ</text>
        )}
        {kind === 'missing' && <circle cx="5" cy="5" r="3" fill="none" stroke={c} strokeWidth="1" strokeDasharray="1 1.2" />}
      </svg>
    </span>
  )
}

/* ─────────────────────────────────────────────────────
   Field — labelled value + provenance glyph
   ───────────────────────────────────────────────────── */
export function Field({
  label, value, prov = 'manual', mono = false, accent = false,
}: { label: string; value: ReactNode; prov?: Provenance; mono?: boolean; accent?: boolean }) {
  return (
    <div className="flex flex-col gap-1 min-w-0">
      <div className="flex items-center gap-1.5">
        <ProvenanceIcon kind={prov} />
        <span className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-3)]">{label}</span>
      </div>
      <div className={`text-sm leading-tight truncate ${mono ? 'font-mono' : ''} ${accent ? 'text-[var(--accent)]' : 'text-[var(--text-1)]'}`}>
        {value}
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────
   IdChip — mono ID with label
   ───────────────────────────────────────────────────── */
export function IdChip({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 border border-[var(--border)] bg-[var(--surface-1)] px-2 py-1 text-[11px] font-mono group hover:border-[var(--border-2)] transition-colors">
      <span className="text-[var(--text-3)] uppercase tracking-wider text-[9px]">{label}</span>
      <span className="text-[var(--text-1)]">{value}</span>
    </span>
  )
}

/* ─────────────────────────────────────────────────────
   Pill — status indicator
   ───────────────────────────────────────────────────── */
export type PillState = 'ok' | 'warn' | 'danger' | 'info' | 'neutral'
export function Pill({ children, state = 'neutral', uppercase = true }: {
  children: ReactNode; state?: PillState; uppercase?: boolean
}) {
  const styles: Record<PillState, string> = {
    ok:      'border-[color:var(--ok)]/40 bg-[color:var(--ok-bg)] text-[color:var(--ok)]',
    warn:    'border-[color:var(--warn-line)] bg-[color:var(--warn-bg)] text-[color:var(--warn)]',
    danger:  'border-[color:var(--danger-line)] bg-[color:var(--danger-bg)] text-[color:var(--danger)]',
    info:    'border-[color:var(--info)]/35 bg-[color:var(--info)]/10 text-[color:var(--info)]',
    neutral: 'border-[var(--border-2)] bg-[var(--surface-2)] text-[var(--text-2)]',
  }
  return (
    <span className={`inline-flex items-center gap-1 border px-1.5 py-0.5 text-[10px] font-mono leading-tight ${uppercase ? 'uppercase tracking-[0.1em]' : ''} ${styles[state]}`}>
      {children}
    </span>
  )
}

/* ─────────────────────────────────────────────────────
   PflegegradRing — score gauge
   ───────────────────────────────────────────────────── */
export function PflegegradRing({ score, trend, size = 84 }: { score: number; trend: number; size?: number }) {
  const stroke = 3
  const r = (size - stroke * 2) / 2
  const c = 2 * Math.PI * r
  const offset = c - (score / 100) * c
  const segments = 60
  const segLen = c / segments

  const trendColor = trend >= 0 ? 'var(--ok)' : 'var(--danger)'

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        {/* tick frame */}
        <circle
          cx={size / 2} cy={size / 2} r={r}
          stroke="var(--border)" strokeWidth={stroke} fill="none"
          strokeDasharray={`1 ${segLen - 1}`}
        />
        <circle
          cx={size / 2} cy={size / 2} r={r}
          stroke="var(--accent)" strokeWidth={stroke} fill="none"
          strokeDasharray={c} strokeDashoffset={offset}
          strokeLinecap="butt"
          style={{ transition: 'stroke-dashoffset 1.2s cubic-bezier(0.16, 1, 0.3, 1)' }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-mono text-[26px] font-medium tabular leading-none text-[var(--text-1)]">{score}</span>
        <span className="text-[8px] font-mono uppercase tracking-[0.15em] text-[var(--text-3)] mt-0.5">/100</span>
      </div>
      <div
        className="absolute -bottom-1 left-1/2 -translate-x-1/2 px-1.5 py-px font-mono text-[10px] tabular bg-[var(--bg)] border border-[var(--border)]"
        style={{ color: trendColor }}
      >
        {trend >= 0 ? '+' : ''}{trend} 30d
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────
   Sparkline — 12-Month line chart
   ───────────────────────────────────────────────────── */
export function Sparkline({ data, w = 140, h = 32, color = 'var(--accent)' }: {
  data: number[]; w?: number; h?: number; color?: string
}) {
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const padX = 1, padY = 3
  const innerW = w - padX * 2
  const innerH = h - padY * 2
  const pts = data.map((v, i) => {
    const x = padX + (i / (data.length - 1)) * innerW
    const y = padY + innerH - ((v - min) / range) * innerH
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })
  const area = `${pts.join(' ')} ${padX + innerW},${padY + innerH} ${padX},${padY + innerH}`
  const last = pts[pts.length - 1].split(',').map(Number)

  return (
    <svg width={w} height={h} className="overflow-visible">
      <polygon points={area} fill={color} opacity="0.16" />
      <polyline points={pts.join(' ')} fill="none" stroke={color} strokeWidth="1.25" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r="2.5" fill={color} />
      <circle cx={last[0]} cy={last[1]} r="5" fill="none" stroke={color} strokeWidth="0.6" opacity="0.5" />
    </svg>
  )
}

/* ─────────────────────────────────────────────────────
   Donut — single-percent ring
   ───────────────────────────────────────────────────── */
export function Donut({ percent, size = 72, color = 'var(--ok)' }: {
  percent: number; size?: number; color?: string
}) {
  const stroke = 5
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const offset = c - (percent / 100) * c
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="var(--border)" strokeWidth={stroke} fill="none" />
        <circle
          cx={size / 2} cy={size / 2} r={r}
          stroke={color} strokeWidth={stroke} fill="none"
          strokeDasharray={c} strokeDashoffset={offset}
          strokeLinecap="butt"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-mono text-base font-medium tabular leading-none">{percent.toFixed(1)}</span>
        <span className="text-[8px] font-mono text-[var(--text-3)] mt-0.5">%</span>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────
   Avatar — initials chip
   ───────────────────────────────────────────────────── */
export function Avatar({ initials, type = 'person', size = 26 }: {
  initials: string; type?: 'person' | 'firm'; size?: number
}) {
  const isFirm = type === 'firm'
  return (
    <div
      className={`inline-flex items-center justify-center font-mono font-medium tabular shrink-0 ${
        isFirm
          ? 'bg-[var(--accent-bg)] border border-[var(--accent-line)] text-[var(--accent)]'
          : 'bg-[var(--surface-3)] border border-[var(--border-2)] text-[var(--text-1)]'
      }`}
      style={{
        width: size, height: size,
        fontSize: size * 0.36,
        letterSpacing: '0.05em',
        borderRadius: isFirm ? 0 : '50%',
      }}
    >
      {initials}
    </div>
  )
}

/* ─────────────────────────────────────────────────────
   SectionCard — frame with eyebrow + corner ticks
   ───────────────────────────────────────────────────── */
export function SectionCard({
  id, eyebrow, title, subtitle, meta, children, padded = true, accent = false,
}: {
  id?: string
  eyebrow: string
  title: ReactNode
  subtitle?: string
  meta?: ReactNode
  children: ReactNode
  padded?: boolean
  accent?: boolean
}) {
  return (
    <section id={id} className={`frame-card ${accent ? 'border-[var(--accent-line)]' : ''}`}>
      <header className="flex items-start justify-between gap-6 px-6 pt-5 pb-3 border-b border-[var(--hairline)]">
        <div className="min-w-0">
          <div className="section-eyebrow mb-1.5">{eyebrow}</div>
          <h2 className="font-display text-[22px] leading-tight font-light text-[var(--text-1)]" style={{ fontVariationSettings: '"opsz" 80' }}>
            {title}
          </h2>
          {subtitle && <p className="text-xs text-[var(--text-3)] mt-1">{subtitle}</p>}
        </div>
        {meta && <div className="shrink-0">{meta}</div>}
      </header>
      <div className={padded ? 'p-6' : ''}>{children}</div>
    </section>
  )
}

/* ─────────────────────────────────────────────────────
   ProvenanceBar — horizontal stacked bar showing source mix
   ───────────────────────────────────────────────────── */
export function ProvenanceBar({ manual, mirror, ai, missing, w = 60 }: {
  manual: number; mirror: number; ai: number; missing: number; w?: number
}) {
  const total = manual + mirror + ai + missing || 1
  const cells = [
    { key: 'manual',  count: manual,  color: 'var(--text-2)' },
    { key: 'mirror',  count: mirror,  color: 'var(--info)' },
    { key: 'ai',      count: ai,      color: 'var(--accent)' },
    { key: 'missing', count: missing, color: 'var(--surface-3)' },
  ]
  return (
    <div className="flex h-1 w-full overflow-hidden" style={{ width: w }}>
      {cells.map(c => (
        c.count > 0 && <div key={c.key} style={{ flex: c.count / total, background: c.color }} />
      ))}
    </div>
  )
}

/* ─────────────────────────────────────────────────────
   formatters
   ───────────────────────────────────────────────────── */
export const fmtEUR = (n: number) =>
  n.toLocaleString('de-DE', { style: 'currency', currency: 'EUR', minimumFractionDigits: 2 })

export const fmtNum = (n: number, frac = 0) =>
  n.toLocaleString('de-DE', { minimumFractionDigits: frac, maximumFractionDigits: frac })
