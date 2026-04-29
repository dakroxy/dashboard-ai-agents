import { useState } from 'react'
import { Header } from '../components/Header'
import { Sidebar } from '../components/Sidebar'
import { DueRadarBanner } from '../components/DueRadarBanner'
import { StammdatenSection } from '../components/StammdatenSection'
import { EinheitenPersonenSection } from '../components/EinheitenPersonenSection'
import { FinanzenSection } from '../components/FinanzenSection'
import { TechnikSection } from '../components/TechnikSection'
import { VersicherungenSection } from '../components/VersicherungenSection'
import { ReviewQueueDrawer } from '../components/ReviewQueueDrawer'

type View = 'voll' | 'kompakt' | 'risiko'

export function SteckbriefPage() {
  const [view, setView] = useState<View>('voll')
  const [drawerOpen, setDrawerOpen] = useState(true)

  const dim = (riskCritical: boolean) =>
    view === 'risiko' && !riskCritical
      ? 'opacity-30 pointer-events-none transition-opacity duration-500'
      : 'opacity-100 transition-opacity duration-500'

  return (
    <>
      <Header view={view} setView={setView} drawerOpen={drawerOpen} setDrawerOpen={setDrawerOpen} />
      <DueRadarBanner />

      <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] xl:grid-cols-[220px_1fr_auto]">
        <Sidebar />

        <main className="min-w-0 px-7 py-7 space-y-6">
          <div className={`fade-up ${dim(false)}`} style={{ animationDelay: '60ms' }}><StammdatenSection /></div>
          <div className={`fade-up ${dim(false)}`} style={{ animationDelay: '120ms' }}><EinheitenPersonenSection /></div>
          <div className={`fade-up ${view === 'kompakt' ? 'hidden' : ''}`} style={{ animationDelay: '180ms' }}><TechnikSection /></div>
          <div className={`fade-up ${dim(false)}`} style={{ animationDelay: '240ms' }}><FinanzenSection /></div>
          <div className={`fade-up ${dim(true)}`} style={{ animationDelay: '300ms' }}><VersicherungenSection /></div>

          <footer className="pt-8 pb-12 mt-8 border-t border-[var(--hairline)]">
            <div className="grid grid-cols-12 gap-8 text-[11px] text-[var(--text-3)]">
              <div className="col-span-12 md:col-span-4">
                <div className="section-eyebrow mb-2">Datenherkunft</div>
                <p className="leading-relaxed">
                  Stammdaten + Finanzen aus <span className="text-[var(--info)]">Impower-Mirror</span> (nightly + Live-Pull).
                  Tickets aus <span className="text-[var(--info)]">Facilioo</span>. PDFs in <span className="text-[var(--text-2)]">SharePoint</span> via Graph-API.
                  Manuelle Felder ueber Steckbrief-Pflege, KI-Vorschlaege ueber Review-Queue.
                </p>
              </div>
              <div className="col-span-12 md:col-span-4">
                <div className="section-eyebrow mb-2">Pflegegrad-Berechnung</div>
                <p className="leading-relaxed">
                  Score 76 / 100 — Cluster-gewichtetes Vollstaendigkeits-Mass. Schwaechen: Cluster 4 (Foto Gas-Absperrung fehlt),
                  Cluster 10 Baurecht (Energieausweis &amp; Grundbuch in Arbeit), Cluster 5 Medien.
                </p>
              </div>
              <div className="col-span-12 md:col-span-4">
                <div className="section-eyebrow mb-2">Versionierung</div>
                <p className="leading-relaxed font-mono tabular text-[10px]">
                  Render: 2026-04-28 14:08:22 CEST · Build steckbrief-island@0.1.0 · Mirror-Run 02:31 OK ·
                  Rev. <span className="text-[var(--text-2)]">8a3f9c12</span>
                </p>
              </div>
            </div>
          </footer>
        </main>

        <ReviewQueueDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
      </div>
    </>
  )
}
