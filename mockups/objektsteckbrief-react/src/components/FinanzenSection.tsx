import { Donut, Field, Pill, ProvenanceIcon, SectionCard, Sparkline, fmtEUR, fmtNum } from './ui'
import { accounts, finance } from '../data/mock'

export function FinanzenSection() {
  return (
    <SectionCard
      id="finanzen"
      eyebrow="Cluster 06 · Finanzen"
      title={<>Konten, Rücklagen, <span className="italic font-light text-[var(--text-2)]">Sonderumlagen</span></>}
      subtitle="Salden live aus Impower-API (Live-Pull bei Anzeige), Rücklagen-Mirror nightly, Sonderumlagen aus Beschluss-Sammlung."
      meta={
        <div className="flex items-center gap-2.5 text-[10px] font-mono uppercase tracking-wider">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--live)] live-dot" />
          <span className="text-[var(--live)]">live</span>
          <span className="text-[var(--text-3)]">· zuletzt 14:08:22</span>
        </div>
      }
    >
      {/* Account tiles */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-px bg-[var(--border)] border border-[var(--border)]">
        {accounts.map((a, i) => (
          <div key={i} className="relative bg-[var(--surface-1)] p-5 group hover:bg-[var(--surface-2)] transition-colors">
            <div className="flex items-start justify-between gap-3 mb-3">
              <div>
                <div className="flex items-center gap-1.5">
                  <ProvenanceIcon kind="mirror" />
                  <span className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-3)]">{a.purpose}</span>
                </div>
                <div className="text-[11px] text-[var(--text-2)] mt-1">{a.bank}</div>
              </div>
              {a.live && (
                <div className="flex items-center gap-1.5 shrink-0">
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--live)] live-dot" />
                  <span className="text-[9px] font-mono uppercase tracking-wider text-[var(--live)]">live</span>
                </div>
              )}
            </div>

            <div className="flex items-baseline gap-2 mb-1">
              <span className="font-mono text-[26px] leading-none font-medium tabular text-[var(--text-1)]">
                {fmtNum(a.balance, 2)}
              </span>
              <span className="text-xs font-mono text-[var(--text-3)]">€</span>
            </div>

            <div className="flex items-center gap-2 text-[11px] font-mono tabular">
              {a.deltaToday !== 0 ? (
                <span style={{ color: a.deltaToday > 0 ? 'var(--ok)' : 'var(--danger)' }}>
                  {a.deltaToday > 0 ? '+' : ''}{fmtNum(a.deltaToday, 2)} € heute
                </span>
              ) : (
                <span className="text-[var(--text-3)]">— heute keine Bewegung</span>
              )}
            </div>

            <div className="mt-3 -mx-1">
              <Sparkline data={a.sparkline} w={240} h={36} />
            </div>

            <div className="mt-2 font-mono text-[10px] text-[var(--text-4)] tabular truncate">{a.iban}</div>
          </div>
        ))}
      </div>

      {/* KPIs row */}
      <div className="grid grid-cols-12 gap-6 mt-6">
        {/* Quota donut */}
        <div className="col-span-12 md:col-span-3 flex items-center gap-4 border border-[var(--border)] p-4">
          <Donut percent={finance.paymentQuotaPct} color="var(--ok)" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.16em] text-[var(--text-3)]">
              <ProvenanceIcon kind="derived" />Hausgeld-Quote
            </div>
            <div className="text-xs text-[var(--text-2)] mt-1.5">12 Monate · 168 Sollstellungen</div>
            <div className="text-[11px] text-[var(--ok)] mt-1 font-mono tabular">+0,8 % vs. Vorjahr</div>
          </div>
        </div>

        {/* Reserve target */}
        <div className="col-span-12 md:col-span-3 border border-[var(--border)] p-4">
          <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.16em] text-[var(--text-3)]">
            <ProvenanceIcon kind="mirror" />Soll-Rücklage / Monat
          </div>
          <div className="font-mono text-[22px] tabular leading-none mt-2">
            {fmtNum(finance.reserveTargetMonthly, 0)} <span className="text-sm text-[var(--text-3)]">€</span>
          </div>
          <div className="text-[11px] text-[var(--text-2)] mt-1.5">
            Ist 12 Mo: <span className="font-mono tabular text-[var(--ok)]">+5,2 %</span> über Plan
          </div>
        </div>

        {/* Wirtschaftsplan & JA-Status */}
        <div className="col-span-12 md:col-span-3 border border-[var(--border)] p-4 flex flex-col justify-between gap-3">
          <Field label="Wirtschaftsplan" prov="mirror" value={
            <Pill state={finance.wirtschaftsplanStatus.state}>{finance.wirtschaftsplanStatus.label}</Pill>
          } />
          <Field label="Jahresabrechnung 2025" prov="mirror" value={
            <Pill state={finance.jahresabrechnungStatus.state}>{finance.jahresabrechnungStatus.label}</Pill>
          } />
        </div>

        {/* Misc derived */}
        <div className="col-span-12 md:col-span-3 border border-[var(--border)] p-4 grid grid-cols-2 gap-3">
          <Field label="Insta-Stau gesch." prov="manual" mono value="42.000 €" />
          <Field label="Schäden 5 J. Σ"     prov="derived" mono value="38.940 €" />
          <Field label="Reserve / MEA"     prov="derived" mono value="218 €" />
          <Field label="Rückbuchungen 12 Mo" prov="mirror" mono value="3" />
        </div>
      </div>

      {/* Sonderumlagen list */}
      <div className="mt-6">
        <div className="flex items-baseline justify-between mb-2.5">
          <div className="flex items-center gap-2">
            <ProvenanceIcon kind="mirror" />
            <span className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-3)]">Sonderumlagen · historisch + geplant</span>
          </div>
          <span className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-3)] tabular">
            Σ erhoben 38.500 € · geplant 145.000 €
          </span>
        </div>
        <div className="border border-[var(--border)] divide-y divide-[var(--hairline)]">
          {finance.sonderumlagen.map((s, i) => {
            const planned = s.status.startsWith('beschluss')
            return (
              <div key={i} className={`flex items-center gap-4 px-4 py-2.5 ${planned ? 'bg-[var(--accent-bg)]' : ''}`}>
                <span className="font-mono text-[10px] tabular text-[var(--text-3)] w-16">{s.date}</span>
                <span className="text-xs text-[var(--text-1)] flex-1">{s.titel}</span>
                <span className="font-mono text-xs tabular text-[var(--text-1)]">{fmtEUR(s.amount)}</span>
                <span className="font-mono text-[11px] tabular text-[var(--text-3)]">
                  {s.paid ? `bezahlt ${fmtEUR(s.paid)}` : '— offen'}
                </span>
                <Pill state={planned ? 'warn' : 'ok'}>{s.status}</Pill>
              </div>
            )
          })}
        </div>
      </div>
    </SectionCard>
  )
}
