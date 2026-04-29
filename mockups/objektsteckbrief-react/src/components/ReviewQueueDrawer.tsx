import { ReactNode } from 'react'
import { reviewQueue } from '../data/mock'

interface Props {
  open: boolean
  onClose: () => void
}

export function ReviewQueueDrawer({ open, onClose }: Props) {
  return (
    <aside
      className={`hidden xl:flex flex-col sticky top-[230px] self-start max-h-[calc(100vh-230px)] border-l border-[var(--border)] bg-[var(--surface-1)] transition-all duration-300 ease-out ${
        open ? 'w-[380px]' : 'w-0 overflow-hidden border-l-0'
      }`}
    >
      <header className="px-5 pt-5 pb-4 border-b border-[var(--border)]">
        <div className="flex items-start justify-between mb-3">
          <div>
            <div className="section-eyebrow mb-1">Review-Queue</div>
            <h2 className="font-display text-[18px] italic font-light leading-tight">
              KI-Vorschläge — der Mensch entscheidet.
            </h2>
          </div>
          <button onClick={onClose} className="text-[var(--text-3)] hover:text-[var(--text-1)] text-lg leading-none p-1">×</button>
        </div>
        <div className="flex items-center justify-between text-[10px] font-mono uppercase tracking-wider text-[var(--text-3)]">
          <span><span className="text-[var(--accent)]">12</span> offen · 38 angenommen 30 d</span>
          <a href="#" className="text-[var(--accent)] hover:underline">Alle ▸</a>
        </div>
        <div className="mt-3 flex items-center gap-1">
          <FilterChip active>Alle</FilterChip>
          <FilterChip>PDF</FilterChip>
          <FilterChip>Chat</FilterChip>
          <FilterChip>Mirror</FilterChip>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
        {reviewQueue.map((q, i) => (
          <SuggestionCard key={q.id} q={q} delay={i * 60} />
        ))}
        <div className="text-center py-4 text-[10px] font-mono uppercase tracking-wider text-[var(--text-4)]">
          + 7 weitere Vorschläge
        </div>
      </div>

      <footer className="px-5 py-3 border-t border-[var(--border)] bg-[var(--bg)] flex items-center justify-between text-[10px] font-mono uppercase tracking-wider text-[var(--text-3)]">
        <span>Annahmequote 30d · <span className="text-[var(--ok)]">87%</span></span>
        <button className="btn">Bulk-Approve</button>
      </footer>
    </aside>
  )
}

function FilterChip({ children, active }: { children: ReactNode; active?: boolean }) {
  return (
    <button className={`px-2 py-1 text-[10px] font-mono uppercase tracking-wider border transition-colors ${
      active
        ? 'bg-[var(--accent)] text-[var(--bg)] border-[var(--accent)]'
        : 'border-[var(--border)] text-[var(--text-2)] hover:border-[var(--border-2)] hover:text-[var(--text-1)]'
    }`}>
      {children}
    </button>
  )
}

function SuggestionCard({ q, delay }: { q: typeof reviewQueue[number]; delay: number }) {
  const sourceColor = q.source === 'pdf' ? 'var(--info)' : q.source === 'chat' ? 'var(--accent)' : 'var(--live)'
  const conf = Math.round(q.confidence * 100)
  return (
    <div className="border border-[var(--border)] bg-[var(--surface-2)] p-3 fade-up hover:border-[var(--border-2)] transition-colors group" style={{ animationDelay: `${delay}ms` }}>
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[9px] font-mono uppercase tracking-[0.14em] text-[var(--text-4)] truncate">
            <span style={{ color: sourceColor }}>
              {q.source === 'pdf' ? '▭ PDF' : q.source === 'chat' ? '◐ Chat' : '↻ Mirror'}
            </span>
            <span className="text-[var(--text-4)] truncate">· {q.target}</span>
          </div>
          <div className="text-xs text-[var(--text-1)] mt-1">{q.label}</div>
        </div>
        <span className="text-[9px] font-mono text-[var(--text-3)] shrink-0">{q.age}</span>
      </div>

      <div className="bg-[var(--bg)] border border-[var(--hairline)] p-2 mb-2">
        <div className="text-[9px] font-mono uppercase tracking-wider text-[var(--text-4)] mb-0.5">Vorschlag</div>
        <div className="text-xs font-mono tabular text-[var(--accent)] leading-tight">{q.proposal}</div>
        {q.current !== '—' && (
          <>
            <div className="text-[9px] font-mono uppercase tracking-wider text-[var(--text-4)] mt-1.5 mb-0.5">Aktuell</div>
            <div className="text-[11px] font-mono tabular text-[var(--text-3)] leading-tight line-through">{q.current}</div>
          </>
        )}
      </div>

      <div className="flex items-center gap-2 mb-2">
        <div className="text-[9px] font-mono uppercase tracking-wider text-[var(--text-4)]">Conf.</div>
        <div className="flex-1 h-1 bg-[var(--surface-3)] relative overflow-hidden">
          <div
            className="absolute inset-y-0 left-0"
            style={{
              width: `${conf}%`,
              background: conf > 90 ? 'var(--ok)' : conf > 75 ? 'var(--accent)' : 'var(--warn)',
            }}
          />
          {/* Threshold marker at 80% */}
          <div className="absolute inset-y-0 w-px bg-[var(--text-4)]" style={{ left: '80%' }} />
        </div>
        <span className="font-mono text-[10px] tabular text-[var(--text-1)]">{conf}%</span>
      </div>

      <div className="text-[10px] text-[var(--text-3)] truncate mb-2.5 font-mono">↳ {q.sourceLabel}</div>

      <div className="grid grid-cols-3 gap-1">
        <button className="btn !py-1.5 !px-1 !text-[9px]">Anpassen</button>
        <button className="btn !py-1.5 !px-1 !text-[9px]">Ablehnen</button>
        <button className="btn btn-primary !py-1.5 !px-1 !text-[9px]">Annehmen</button>
      </div>
    </div>
  )
}
