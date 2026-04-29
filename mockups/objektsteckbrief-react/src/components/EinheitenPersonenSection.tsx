import { Pill, ProvenanceIcon, SectionCard, fmtNum } from './ui'
import { units } from '../data/mock'

export function EinheitenPersonenSection() {
  return (
    <SectionCard
      id="einheiten"
      eyebrow="Cluster 02 + 03 · Einheiten · Personen"
      title={<>14 Wohn- und Gewerbe­einheiten, <span className="italic font-light text-[var(--text-2)]">11 Mietverhältnisse</span></>}
      subtitle="Auszug — die vollständige Liste öffnet die WE-Tabellenansicht."
      meta={
        <div className="flex items-center gap-3 text-[10px] font-mono uppercase tracking-wider text-[var(--text-3)]">
          <span>Σ 1 124 m² Wohnfl.</span>
          <span className="text-[var(--text-4)]">·</span>
          <span>Vermietungs­quote 91%</span>
        </div>
      }
    >
      <div className="grid grid-cols-12 gap-6">
        {/* Units sample */}
        <div className="col-span-12 lg:col-span-7">
          <div className="flex items-baseline justify-between mb-2.5">
            <div className="flex items-center gap-2">
              <ProvenanceIcon kind="mirror" />
              <span className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-3)]">Einheiten · Auszug</span>
            </div>
            <a href="#" className="text-[10px] font-mono uppercase tracking-wider text-[var(--accent)] hover:underline">
              Alle 14 WE ▸
            </a>
          </div>
          <div className="border border-[var(--border)]">
            <table className="w-full text-xs">
              <thead className="bg-[var(--surface-2)] border-b border-[var(--border)]">
                <tr className="text-[10px] uppercase tracking-[0.12em] text-[var(--text-3)]">
                  <th className="text-left font-medium px-3 py-2 w-16">WE</th>
                  <th className="text-left font-medium px-3 py-2">Typ</th>
                  <th className="text-right font-medium px-3 py-2 w-20">m²</th>
                  <th className="text-right font-medium px-3 py-2 w-16">Räume</th>
                  <th className="text-left font-medium px-3 py-2 w-20">Etage</th>
                  <th className="text-left font-medium px-3 py-2">Mieter</th>
                  <th className="text-left font-medium px-3 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {units.map((u, i) => (
                  <tr key={i} className="border-b border-[var(--hairline)] last:border-0 hover:bg-[var(--surface-2)]/60 transition-colors">
                    <td className="px-3 py-2 font-mono tabular text-[var(--accent)]">{u.nr}</td>
                    <td className="px-3 py-2 text-[var(--text-2)]">{u.type}</td>
                    <td className="px-3 py-2 text-right font-mono tabular text-[var(--text-1)]">{fmtNum(u.sqm, 1)}</td>
                    <td className="px-3 py-2 text-right font-mono tabular text-[var(--text-2)]">{u.rooms.toFixed(1)}</td>
                    <td className="px-3 py-2 font-mono text-[10px] tabular text-[var(--text-3)]">{u.floor}</td>
                    <td className="px-3 py-2 text-[var(--text-1)] truncate">{u.tenant}</td>
                    <td className="px-3 py-2">
                      <Pill state={u.status === 'vermietet' ? 'ok' : u.status === 'eigengenutzt' ? 'info' : 'warn'}>
                        {u.status}
                      </Pill>
                    </td>
                  </tr>
                ))}
                <tr className="border-t border-[var(--border)] bg-[var(--surface-2)]/40">
                  <td colSpan={7} className="px-3 py-2 text-[10px] font-mono uppercase tracking-wider text-[var(--text-3)] text-center">
                    + 11 weitere Einheiten — Vollansicht öffnen
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* People summary */}
        <div className="col-span-12 lg:col-span-5">
          <div className="section-eyebrow mb-2.5">Personen-Aggregation</div>
          <div className="border border-[var(--border)] divide-y divide-[var(--hairline)]">
            <PersonSummaryRow label="Eigentümer" value="6 Parteien" detail="3 Multi-WEG · 1 Erbengem." prov="mirror" />
            <PersonSummaryRow label="Mieter aktiv" value="11" detail="2 Untermieter · 1 Gewerbe" prov="mirror" />
            <PersonSummaryRow label="Beirat" value="2" detail="Sievertsen, Kroll" prov="manual" />
            <PersonSummaryRow label="Offene Tickets" value="3" detail="2 Eppendorf-Mieter · 1 Eig." prov="mirror" warn />
            <PersonSummaryRow label="Notizen intern" value="4 Eintr." detail="zuletzt 2026-04-19" prov="manual" />
          </div>
          <div className="mt-3 text-[10px] font-mono uppercase tracking-wider text-[var(--text-3)] flex items-center gap-2">
            <ProvenanceIcon kind="mirror" />
            Tickets via Facilioo-Live-Pull
          </div>
        </div>
      </div>
    </SectionCard>
  )
}

function PersonSummaryRow({ label, value, detail, prov, warn }: {
  label: string; value: string; detail: string; prov: 'manual' | 'mirror'; warn?: boolean
}) {
  return (
    <div className="grid grid-cols-[1fr_auto_2fr] items-center gap-4 px-4 py-2.5">
      <div className="flex items-center gap-2">
        <ProvenanceIcon kind={prov} />
        <span className="text-xs text-[var(--text-2)]">{label}</span>
      </div>
      <span className={`font-mono text-base tabular ${warn ? 'text-[var(--warn)]' : 'text-[var(--text-1)]'}`}>{value}</span>
      <span className="text-[11px] text-[var(--text-3)] truncate">{detail}</span>
    </div>
  )
}
