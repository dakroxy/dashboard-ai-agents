import { Pill, ProvenanceIcon, SectionCard, fmtNum } from './ui'
import { policies, obligations, damages } from '../data/mock'

export function VersicherungenSection() {
  return (
    <SectionCard
      id="versicherungen"
      eyebrow="Cluster 08 · Versicherungen & Wartungspflichten"
      title={<>Policen, Wartungs­nachweise, <span className="italic font-light text-[var(--text-2)]">Schadens­historie</span></>}
      subtitle="Steckbrief-Truth. Wartungsnachweise sind Deckungs-Bedingung — Lücken bedeuten Versicherungs­ausfall."
      meta={
        <div className="flex items-center gap-3 text-[10px] font-mono uppercase tracking-wider">
          <span className="text-[var(--danger)]">1 überfällig</span>
          <span className="text-[var(--text-4)]">·</span>
          <span className="text-[var(--warn)]">2 in 60 d</span>
          <span className="text-[var(--text-4)]">·</span>
          <span className="text-[var(--text-3)]">5 Schäden 5J · 30.540 € reg.</span>
        </div>
      }
    >
      {/* Policies table */}
      <div className="mb-6">
        <div className="flex items-baseline justify-between mb-2.5">
          <div className="flex items-center gap-2">
            <ProvenanceIcon kind="manual" />
            <span className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-3)]">Policen-Portfolio · 4 aktiv · Σ Beitrag p.a. 9.262,50 €</span>
          </div>
          <a href="#" className="text-[10px] font-mono uppercase tracking-wider text-[var(--accent)] hover:underline">
            Versicherer-Registry ▸
          </a>
        </div>
        <div className="border border-[var(--border)]">
          <table className="w-full text-xs">
            <thead className="bg-[var(--surface-2)] border-b border-[var(--border)]">
              <tr className="text-[10px] uppercase tracking-[0.12em] text-[var(--text-3)]">
                <th className="text-left font-medium px-3 py-2 w-44">Versicherer · Typ</th>
                <th className="text-left font-medium px-3 py-2 w-40">Policen-Nr.</th>
                <th className="text-right font-medium px-3 py-2">Vers.-Summe</th>
                <th className="text-right font-medium px-3 py-2 w-20">SB</th>
                <th className="text-right font-medium px-3 py-2 w-28">Beitrag p.a.</th>
                <th className="text-left font-medium px-3 py-2 w-40">Ablauf</th>
              </tr>
            </thead>
            <tbody>
              {policies.map((p, i) => {
                const due = p.daysToEnd <= 60
                return (
                  <tr
                    key={i}
                    className={`border-b border-[var(--hairline)] last:border-0 transition-colors hover:bg-[var(--surface-2)]/60 ${due ? 'bg-[var(--warn-bg)]/40' : ''}`}
                  >
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2.5">
                        <span className="inline-flex items-center justify-center w-6 h-6 border border-[var(--border-2)] bg-[var(--surface-1)] font-mono text-[11px] font-medium text-[var(--text-1)]">
                          {p.insurerInitial}
                        </span>
                        <div>
                          <div className="text-[var(--text-1)]">{p.insurer}</div>
                          <div className="text-[10px] text-[var(--text-3)]">{p.type}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-2.5 font-mono text-[10px] tabular text-[var(--text-2)]">{p.number}</td>
                    <td className="px-3 py-2.5 text-right font-mono tabular text-[var(--text-1)]">{p.sum}</td>
                    <td className="px-3 py-2.5 text-right font-mono tabular text-[var(--text-3)]">
                      {p.deductible ? `${fmtNum(p.deductible, 0)} €` : '—'}
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono tabular text-[var(--text-1)]">
                      {fmtNum(p.premium, 2)} €
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <span className="font-mono tabular text-[var(--text-2)]">{p.end}</span>
                        {due ? (
                          <Pill state={p.daysToEnd < 30 ? 'danger' : 'warn'}>
                            <CountdownDot /> in {p.daysToEnd} d
                          </Pill>
                        ) : (
                          <span className="text-[10px] font-mono text-[var(--text-3)] tabular">+ {p.daysToEnd} d</span>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Obligations + Damages side-by-side */}
      <div className="grid grid-cols-12 gap-6">
        {/* Wartungspflichten */}
        <div className="col-span-12 lg:col-span-7">
          <div className="flex items-baseline justify-between mb-2.5">
            <div className="flex items-center gap-2">
              <ProvenanceIcon kind="manual" />
              <span className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-3)]">Wartungspflichten</span>
            </div>
            <span className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-3)]">
              5 Pflichten · 1 überfällig · 1 unbekannt
            </span>
          </div>
          <div className="border border-[var(--border)] divide-y divide-[var(--hairline)]">
            {obligations.map((o, i) => (
              <ObligationRow key={i} {...o} />
            ))}
          </div>
        </div>

        {/* Schadenshistorie */}
        <div className="col-span-12 lg:col-span-5">
          <div className="flex items-baseline justify-between mb-2.5">
            <div className="flex items-center gap-2">
              <ProvenanceIcon kind="manual" />
              <span className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-3)]">Schadens­historie · 5 Jahre</span>
            </div>
            <span className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-3)] tabular">
              Σ 30.540 €
            </span>
          </div>
          <div className="border border-[var(--border)] divide-y divide-[var(--hairline)]">
            {damages.map((d, i) => (
              <div key={i} className="grid grid-cols-[64px_1fr_auto_auto] items-center gap-3 px-3 py-2 text-xs">
                <span className="font-mono text-[10px] tabular text-[var(--text-3)]">{d.date}</span>
                <div className="min-w-0">
                  <div className="text-[var(--text-1)] truncate">{d.type}</div>
                  <div className="text-[10px] font-mono text-[var(--text-3)]">{d.unit} · {d.ref}</div>
                </div>
                <span className="font-mono tabular text-[var(--text-2)] text-[11px] whitespace-nowrap">
                  {fmtNum(d.settled, 0)} <span className="text-[var(--text-4)]">/ {fmtNum(d.claim, 0)}</span> €
                </span>
                <Pill state={d.status === 'reguliert' ? 'ok' : 'danger'}>{d.status}</Pill>
              </div>
            ))}
          </div>
        </div>
      </div>
    </SectionCard>
  )
}

function ObligationRow({ type, last, next, status, provider, overdueBy, daysTo }: {
  type: string; last: string; next: string; status: 'ok' | 'overdue' | 'soon' | 'unknown';
  provider: string; overdueBy?: number; daysTo?: number
}) {
  const stateMap = {
    ok: { color: 'var(--ok)', label: 'OK' },
    overdue: { color: 'var(--danger)', label: 'ÜBERFÄLLIG' },
    soon: { color: 'var(--warn)', label: 'BALD FÄLLIG' },
    unknown: { color: 'var(--text-4)', label: 'UNBEKANNT' },
  }[status]

  return (
    <div className={`grid grid-cols-[8px_140px_1fr_140px_120px_auto] items-center gap-4 px-4 py-2.5 ${
      status === 'overdue' ? 'bg-[var(--danger-bg)]/50' : status === 'soon' ? 'bg-[var(--warn-bg)]/30' : ''
    }`}>
      <span className="block w-[3px] h-6" style={{ background: stateMap.color }} />
      <div className="text-xs text-[var(--text-1)]">{type}</div>
      <div className="text-[11px] text-[var(--text-3)] truncate">
        {provider !== '—' ? <>Anbieter <span className="text-[var(--text-2)]">{provider}</span></> : <span className="text-[var(--text-4)]">— kein Anbieter</span>}
      </div>
      <div className="font-mono text-[11px] tabular text-[var(--text-2)]">
        letzte: <span className="text-[var(--text-1)]">{last}</span>
      </div>
      <div className="font-mono text-[11px] tabular text-[var(--text-2)]">
        nächste: <span className="text-[var(--text-1)]">{next}</span>
      </div>
      <div className="font-mono text-[10px] tabular tracking-wider whitespace-nowrap" style={{ color: stateMap.color }}>
        {status === 'overdue' && overdueBy ? `+${overdueBy} d ÜBER` :
         status === 'soon' && daysTo ? `in ${daysTo} d` :
         stateMap.label}
      </div>
    </div>
  )
}

function CountdownDot() {
  return <span className="inline-block w-1.5 h-1.5 rounded-full bg-current animate-pulse mr-0.5" />
}
