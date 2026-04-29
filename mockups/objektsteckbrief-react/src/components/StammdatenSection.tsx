import { Avatar, Field, ProvenanceIcon, SectionCard } from './ui'
import { objekt, owners } from '../data/mock'

export function StammdatenSection() {
  return (
    <SectionCard
      id="stammdaten"
      eyebrow="Cluster 01 · Stammdaten"
      title={<>Identität, Adresse, <span className="italic font-light text-[var(--text-2)]">Eigentümer­struktur</span></>}
      subtitle="Read-only Spiegel aus Impower (Stand: heute, 02:31). Notes-Felder werden manuell gepflegt."
      meta={
        <div className="flex items-center gap-3 text-[10px] font-mono uppercase tracking-wider text-[var(--text-3)]">
          <span>10/10 Felder</span>
          <span className="text-[var(--text-4)]">·</span>
          <span className="text-[var(--info)]">8 ↻</span>
          <span className="text-[var(--text-2)]">2 ◼</span>
        </div>
      }
    >
      <div className="grid grid-cols-12 gap-x-8 gap-y-5">
        {/* Address block */}
        <div className="col-span-12 lg:col-span-4 grid grid-cols-2 gap-y-5 gap-x-6">
          <Field label="Straße" prov="mirror" value={objekt.street} />
          <Field label="Land"   prov="mirror" value={objekt.country} />
          <Field label="PLZ / Ort" prov="mirror" value={objekt.city} />
          <Field label="WEG-Nr. (intern)" prov="manual" value={objekt.wegNumberIntern} mono />
          <Field label="Anzahl Einheiten" prov="derived" value={`${objekt.unitCount} WE`} mono />
          <Field label="Gesamt-MEA"     prov="derived" value={objekt.totalMea} mono />
        </div>

        {/* Owners table */}
        <div className="col-span-12 lg:col-span-8">
          <div className="flex items-center justify-between mb-2.5">
            <div className="flex items-center gap-2">
              <ProvenanceIcon kind="mirror" />
              <span className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-3)]">
                Eigentümer mit Stimmrechten · {owners.length} Parteien · 14 Stimmen gesamt
              </span>
            </div>
            <a href="#" className="text-[10px] font-mono uppercase tracking-wider text-[var(--accent)] hover:underline">
              Vollständige Liste ▸
            </a>
          </div>
          <div className="border border-[var(--border)]">
            <table className="w-full text-xs">
              <thead className="bg-[var(--surface-2)] border-b border-[var(--border)]">
                <tr className="text-[10px] uppercase tracking-[0.12em] text-[var(--text-3)]">
                  <th className="text-left font-medium px-3 py-2 w-10"></th>
                  <th className="text-left font-medium px-3 py-2">Name</th>
                  <th className="text-right font-medium px-3 py-2 w-24">MEA</th>
                  <th className="text-right font-medium px-3 py-2 w-20">Stimmen</th>
                  <th className="text-left font-medium px-3 py-2">Hinweis</th>
                </tr>
              </thead>
              <tbody>
                {owners.map((o, i) => (
                  <tr
                    key={i}
                    className="border-b border-[var(--hairline)] last:border-0 hover:bg-[var(--surface-2)]/60 transition-colors group"
                  >
                    <td className="px-3 py-2">
                      <Avatar initials={o.initials} type={o.type} />
                    </td>
                    <td className="px-3 py-2 text-[var(--text-1)]">
                      {o.name}
                      {o.type === 'firm' && (
                        <span className="ml-2 text-[9px] font-mono uppercase tracking-wider text-[var(--accent)] border border-[var(--accent-line)] px-1 align-middle">
                          juristisch
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular text-[var(--text-1)]">{o.mea}</td>
                    <td className="px-3 py-2 text-right font-mono tabular text-[var(--text-1)]">{o.stimmen}</td>
                    <td className="px-3 py-2 text-[var(--text-2)] truncate max-w-[280px]">
                      {o.notes ? (
                        <>
                          <ProvenanceIcon kind="manual" />
                          <span className="ml-1.5">{o.notes}</span>
                        </>
                      ) : (
                        <span className="text-[var(--text-4)]">— keine internen Notizen</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </SectionCard>
  )
}
