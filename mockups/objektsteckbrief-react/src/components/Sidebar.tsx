import { ProvenanceBar } from './ui'
import { sectionProvenance, SectionKey } from '../data/mock'

interface NavItem {
  id: string
  label: string
  key: SectionKey | null
  hint?: string
}

const items: NavItem[] = [
  { id: 'stammdaten',      label: 'Stammdaten',           key: 'stammdaten' },
  { id: 'einheiten',       label: 'Einheiten',            key: 'einheiten',  hint: '14 WE' },
  { id: 'personen',        label: 'Personen',             key: 'personen',   hint: '6 ET · 11 MT' },
  { id: 'technik',         label: 'Technik & Substanz',   key: 'technik' },
  { id: 'medien',          label: 'Medien · DMS',         key: 'medien',     hint: 'SharePoint' },
  { id: 'finanzen',        label: 'Finanzen',             key: 'finanzen' },
  { id: 'vertrag',         label: 'Verwaltervertrag',     key: 'vertrag' },
  { id: 'versicherungen',  label: 'Versicherungen',       key: 'versicherungen', hint: '4 Policen' },
  { id: 'recht',           label: 'Recht & Governance',   key: 'recht' },
  { id: 'baurecht',        label: 'Baurecht / DD',        key: 'baurecht' },
]

export function Sidebar() {
  return (
    <nav className="hidden lg:flex flex-col sticky top-[230px] self-start max-h-[calc(100vh-230px)] overflow-y-auto px-4 pt-5 pb-8 border-r border-[var(--border)] bg-[var(--bg)]">
      <div className="section-eyebrow mb-3 px-1">Sektionen</div>
      <ol className="flex flex-col gap-px">
        {items.map((it, i) => {
          const prov = it.key ? sectionProvenance[it.key] : null
          return (
            <li key={it.id}>
              <a
                href={`#${it.id}`}
                className="group block py-2 px-2 hover:bg-[var(--surface-2)] transition-colors border-l-2 border-transparent hover:border-[var(--accent)]"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-xs text-[var(--text-2)] group-hover:text-[var(--text-1)] truncate">
                    <span className="font-mono text-[10px] text-[var(--text-4)] mr-1.5 tabular">{String(i + 1).padStart(2, '0')}</span>
                    {it.label}
                  </span>
                  {it.hint && <span className="text-[9px] font-mono text-[var(--text-4)] tabular shrink-0">{it.hint}</span>}
                </div>
                {prov && (
                  <div className="mt-1.5 ml-5">
                    <ProvenanceBar {...prov} w={120} />
                  </div>
                )}
              </a>
            </li>
          )
        })}
      </ol>

      {/* Legend */}
      <div className="mt-6 pt-4 border-t border-[var(--hairline)] px-1">
        <div className="section-eyebrow mb-2.5">Provenance</div>
        <ul className="text-[10px] text-[var(--text-3)] space-y-1.5">
          <li className="flex items-center gap-2"><span className="w-2 h-2" style={{ background: 'var(--text-2)' }} />manuell</li>
          <li className="flex items-center gap-2"><span className="w-2 h-2" style={{ background: 'var(--info)' }} />Impower-Spiegel</li>
          <li className="flex items-center gap-2"><span className="w-2 h-2" style={{ background: 'var(--accent)' }} />KI-Vorschlag</li>
          <li className="flex items-center gap-2"><span className="w-2 h-2 border" style={{ borderColor: 'var(--text-4)' }} />leer</li>
        </ul>
      </div>
    </nav>
  )
}
