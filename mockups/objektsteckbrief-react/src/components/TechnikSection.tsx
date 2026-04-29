import { useState } from 'react'
import { Field, Pill, ProvenanceIcon, SectionCard } from './ui'
import { technik } from '../data/mock'
import { HistorieTimeline } from './HistorieTimeline'

export function TechnikSection() {
  return (
    <SectionCard
      id="technik"
      eyebrow="Cluster 04 · Technik & Gebäudesubstanz"
      title={<>Absperrpunkte, Heizung, Zugang, <span className="italic font-light text-[var(--text-2)]">Bauakte</span></>}
      subtitle="Steckbrief-Truth — komplett intern gepflegt, foto-zentriert. Wert für den 2-Uhr-nachts-Notfall."
      meta={
        <div className="flex items-center gap-3 text-[10px] font-mono uppercase tracking-wider text-[var(--text-3)]">
          <span>13/16 Felder</span>
          <span className="text-[var(--text-4)]">·</span>
          <span className="text-[var(--text-2)]">11 ◼</span>
          <span className="text-[var(--accent)]">2 ✦</span>
          <span className="text-[var(--danger)]">3 leer</span>
        </div>
      }
    >
      {/* Shutoffs row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-px bg-[var(--border)] border border-[var(--border)]">
        {technik.shutoffs.map((s, i) => <ShutoffCard key={i} kind={s.kind} location={s.location} photoStatus={s.photoStatus} lastVerified={s.lastVerified} />)}
      </div>

      {/* Heating + Access codes */}
      <div className="grid grid-cols-12 gap-6 mt-6">
        <div className="col-span-12 lg:col-span-8 border border-[var(--border)] p-5 relative">
          <div className="absolute top-3 right-3 flex items-center gap-2 text-[10px] font-mono uppercase tracking-wider">
            <ProvenanceIcon kind="ai" />
            <span className="text-[var(--accent)]">Bj. via PDF-Extraktion · 0,92</span>
          </div>
          <div className="section-eyebrow mb-3">Heizung · Steckbrief</div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-4">
            <Field label="Typ"             prov="manual" value={technik.heating.type} />
            <Field label="Hersteller"      prov="manual" value={technik.heating.manufacturer} />
            <Field label="Baujahr"         prov="ai"     mono accent value={technik.heating.yearInstalled} />
            <Field label="Standort"        prov="manual" value={technik.heating.location} />
            <Field label="Wartungsfirma"   prov="manual" value={
              <a href="#" className="hover:underline underline-offset-4 decoration-[var(--accent)] flex items-center gap-1.5">
                {technik.heating.serviceProvider}
                <span className="text-[9px] font-mono text-[var(--text-3)]">▸ Profil</span>
              </a>
            } />
            <Field label="Stör-Hotline"    prov="manual" mono value={technik.heating.faultHotline} />
          </div>
          <div className="mt-4 pt-3 border-t border-[var(--hairline)] flex items-center gap-3 text-[10px] font-mono uppercase tracking-wider text-[var(--text-3)]">
            <Pill state="ok">Wartung 2025-11 OK</Pill>
            <Pill state="warn">Modernisierung 2026 in Beschluss-Vorbereitung</Pill>
            <span className="ml-auto text-[var(--text-4)]">letzte Begehung 2025-11-04 · Bauer (Verwalter)</span>
          </div>
        </div>

        <div className="col-span-12 lg:col-span-4 border border-[var(--border)] p-5">
          <div className="section-eyebrow mb-3">Zugangscodes</div>
          <div className="space-y-2.5">
            {technik.accessCodes.map((c, i) => (
              <AccessCodeRow key={i} {...c} />
            ))}
          </div>
          <div className="mt-4 pt-3 border-t border-[var(--hairline)] flex items-center gap-2 text-[10px] font-mono uppercase tracking-wider text-[var(--text-3)]">
            <LockSvg />
            verschlüsselt · KMS · letzte Rotation 2025-09
          </div>
        </div>
      </div>

      {/* Bauakten timeline — the killer */}
      <HistorieTimeline />
    </SectionCard>
  )
}

function ShutoffCard({ kind, location, photoStatus, lastVerified }: {
  kind: string; location: string; photoStatus: 'present' | 'missing'; lastVerified: string
}) {
  const missing = photoStatus === 'missing'
  return (
    <div className="bg-[var(--surface-1)] p-4 group hover:bg-[var(--surface-2)] transition-colors">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="flex items-center gap-1.5">
            <ProvenanceIcon kind={missing ? 'missing' : 'manual'} />
            <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--text-3)]">Absperrung</span>
          </div>
          <div className="font-display text-[18px] italic font-light text-[var(--text-1)] mt-0.5">{kind}</div>
        </div>
        {missing
          ? <Pill state="danger">Foto fehlt</Pill>
          : <Pill state="ok">verifiziert</Pill>
        }
      </div>

      {/* Foto-Slot */}
      <div className={`relative h-28 mb-3 border ${missing ? 'border-dashed border-[var(--danger-line)] bg-[var(--danger-bg)]' : 'border-[var(--border-2)] bg-[var(--surface-3)]'}`}>
        {missing ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5">
            <CameraOffSvg />
            <span className="text-[10px] font-mono uppercase tracking-wider text-[var(--danger)]">Foto fehlt</span>
            <button className="text-[10px] font-mono text-[var(--accent)] hover:underline">Hochladen ▸</button>
          </div>
        ) : (
          <FakePhoto kind={kind} />
        )}
        <div className="absolute bottom-1.5 left-1.5 flex items-center gap-1 text-[9px] font-mono text-[var(--text-3)] bg-[var(--bg)]/70 px-1.5 py-0.5">
          <CalendarSvg />
          {lastVerified !== '—' ? lastVerified : '—'}
        </div>
      </div>

      <div className="text-xs text-[var(--text-2)] leading-snug">{location}</div>
    </div>
  )
}

function AccessCodeRow({ label, value, encrypted }: { label: string; value: string; encrypted: boolean }) {
  const [revealed, setRevealed] = useState(false)
  return (
    <div className="flex items-center justify-between gap-2 px-3 py-2 border border-[var(--hairline)] hover:border-[var(--border)] transition-colors group">
      <div className="flex items-center gap-2 text-xs text-[var(--text-2)]">
        {encrypted ? <LockSvg /> : <span className="text-[var(--text-4)] text-[10px] font-mono uppercase">n/a</span>}
        <span>{label}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="font-mono text-sm text-[var(--text-1)] tabular tracking-widest">
          {encrypted ? (revealed ? '4∙7∙2∙9' : '••••') : value}
        </span>
        {encrypted && (
          <button
            onClick={() => setRevealed(!revealed)}
            className="text-[9px] font-mono uppercase tracking-wider text-[var(--accent)] hover:underline"
          >
            {revealed ? 'verbergen' : 'enthüllen'}
          </button>
        )}
      </div>
    </div>
  )
}

function LockSvg() {
  return (
    <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="var(--text-3)" strokeWidth="1.2">
      <rect x="2" y="5" width="8" height="6" />
      <path d="M4 5 V3.5 a2 2 0 0 1 4 0 V5" />
    </svg>
  )
}

function CameraOffSvg() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--danger)" strokeWidth="1.2">
      <path d="M3 5l18 14M9 4h6l1.5 2H21v12M3 6v12h12" />
      <circle cx="12" cy="13" r="3" />
    </svg>
  )
}

function CalendarSvg() {
  return (
    <svg width="9" height="9" viewBox="0 0 12 12" fill="none" stroke="var(--text-3)" strokeWidth="1.2">
      <rect x="1.5" y="3" width="9" height="7.5" />
      <line x1="1.5" y1="5.5" x2="10.5" y2="5.5" />
      <line x1="4" y1="2" x2="4" y2="4" />
      <line x1="8" y1="2" x2="8" y2="4" />
    </svg>
  )
}

// Atmospheric "photo" placeholder via SVG only — no stock images
function FakePhoto({ kind }: { kind: string }) {
  const palette = kind === 'Wasser'
    ? ['#1c2738', '#2a3a52', '#345575', '#7d92b8']
    : ['#2c2419', '#403422', '#5a472d', '#a18256']
  return (
    <svg viewBox="0 0 200 80" className="w-full h-full" preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id={`p-${kind}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={palette[0]} />
          <stop offset="60%" stopColor={palette[1]} />
          <stop offset="100%" stopColor={palette[2]} />
        </linearGradient>
        <pattern id={`tile-${kind}`} patternUnits="userSpaceOnUse" width="20" height="20">
          <line x1="0" y1="0" x2="20" y2="0" stroke={palette[0]} strokeWidth="0.5" opacity="0.6" />
          <line x1="0" y1="0" x2="0" y2="20" stroke={palette[0]} strokeWidth="0.5" opacity="0.6" />
        </pattern>
      </defs>
      <rect width="200" height="80" fill={`url(#p-${kind})`} />
      <rect width="200" height="80" fill={`url(#tile-${kind})`} opacity="0.5" />
      {/* Pipe / valve abstract */}
      <g stroke={palette[3]} strokeWidth="3" fill="none" opacity="0.7">
        <line x1="20" y1="20" x2="180" y2="20" />
        <circle cx="100" cy="20" r="9" fill={palette[2]} />
        <line x1="100" y1="11" x2="100" y2="29" />
      </g>
      <text x="194" y="74" fontSize="7" fontFamily="IBM Plex Mono" fill={palette[3]} textAnchor="end" letterSpacing="0.08em" opacity="0.6">
        IMG_HAM61_{kind.toUpperCase()}_001
      </text>
    </svg>
  )
}
