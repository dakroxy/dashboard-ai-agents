import { useState, useMemo } from 'react'
import {
  DndContext, DragEndEvent, DragOverlay, DragStartEvent,
  PointerSensor, useSensor, useSensors, closestCorners, useDroppable,
} from '@dnd-kit/core'
import { useSortable, SortableContext, verticalListSortingStrategy, arrayMove } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { buckets, dueItems, objectsForFilter, Bucket, DueItem, ItemKind } from '../data/dueRadar'
import { Avatar, fmtEUR } from '../components/ui'

type FilterState = {
  object: string | 'all'
  kind: ItemKind | 'all'
  responsible: string | 'all'
}

const kindLabels: Record<ItemKind, string> = {
  wartung: 'Wartung',
  police: 'Police',
  vertrag: 'Vertrag',
  beschluss: 'Beschluss',
  pruefung: 'Prüfung',
}

const kindGlyph: Record<ItemKind, string> = {
  wartung: '⛟', police: '⌖', vertrag: '§', beschluss: '⚖', pruefung: '✓',
}

export function DueRadarPage() {
  const [items, setItems] = useState<DueItem[]>(dueItems)
  const [filter, setFilter] = useState<FilterState>({ object: 'all', kind: 'all', responsible: 'all' })
  const [activeId, setActiveId] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))

  const filtered = useMemo(() => items.filter(it =>
    (filter.object === 'all' || it.objectCode === filter.object) &&
    (filter.kind === 'all' || it.kind === filter.kind) &&
    (filter.responsible === 'all' || it.responsibleInitials === filter.responsible)
  ), [items, filter])

  const byBucket = useMemo(() => {
    const m: Record<Bucket, DueItem[]> = {
      overdue: [], d30: [], d60: [], d90: [], d180: [], ok: [],
    }
    filtered.forEach(it => m[it.bucket].push(it))
    // Pinned first, then by daysDelta
    Object.values(m).forEach(list => list.sort((a, b) =>
      (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0) || a.daysDelta - b.daysDelta))
    return m
  }, [filtered])

  const counts = useMemo(() => buckets.map(b => ({
    ...b, count: byBucket[b.id].length, totalCount: items.filter(i => i.bucket === b.id).length
  })), [byBucket, items])

  const totals = useMemo(() => ({
    overdue: items.filter(i => i.bucket === 'overdue').length,
    impactValue: items.filter(i => i.amount).reduce((s, i) => s + (i.amount || 0), 0),
    objects: new Set(items.map(i => i.objectCode)).size,
  }), [items])

  const responsibles = useMemo(() => {
    const m = new Map<string, string>()
    items.forEach(i => m.set(i.responsibleInitials, i.responsible))
    return Array.from(m.entries())
  }, [items])

  function onDragStart(e: DragStartEvent) {
    setActiveId(String(e.active.id))
  }

  function onDragEnd(e: DragEndEvent) {
    setActiveId(null)
    const { active, over } = e
    if (!over) return

    const activeItem = items.find(i => i.id === active.id)
    if (!activeItem) return

    // Dropped onto a column directly
    if (typeof over.id === 'string' && over.id.startsWith('col-')) {
      const targetBucket = over.id.replace('col-', '') as Bucket
      if (targetBucket !== activeItem.bucket) {
        setItems(prev => prev.map(i => i.id === activeItem.id ? { ...i, bucket: targetBucket } : i))
      }
      return
    }

    // Dropped onto another card
    const overItem = items.find(i => i.id === over.id)
    if (!overItem) return

    if (activeItem.bucket === overItem.bucket) {
      // Reorder within column
      setItems(prev => {
        const colIds = byBucket[activeItem.bucket].map(i => i.id)
        const oldIdx = colIds.indexOf(activeItem.id)
        const newIdx = colIds.indexOf(overItem.id)
        if (oldIdx < 0 || newIdx < 0) return prev
        const reordered = arrayMove(byBucket[activeItem.bucket], oldIdx, newIdx)
        const others = prev.filter(i => i.bucket !== activeItem.bucket)
        return [...others, ...reordered]
      })
    } else {
      // Move to different bucket
      setItems(prev => prev.map(i => i.id === activeItem.id ? { ...i, bucket: overItem.bucket } : i))
    }
  }

  const activeItem = activeId ? items.find(i => i.id === activeId) : null
  const selectedItem = selectedId ? items.find(i => i.id === selectedId) : null

  return (
    <>
      {/* Page header */}
      <header className="sticky top-[37px] z-40 bg-[var(--bg)]/95 backdrop-blur border-b border-[var(--border)]">
        <div className="px-7 pt-5 pb-4">
          <div className="flex items-end justify-between gap-8 mb-4">
            <div>
              <div className="section-eyebrow mb-1">Querschnitt · Cluster 12 · alle Objekte</div>
              <h1 className="font-display text-[28px] leading-tight font-light">
                Due-Radar — <span className="italic">was diese Woche, dieser Monat, dieses Quartal kippt.</span>
              </h1>
              <p className="text-xs text-[var(--text-3)] mt-1.5 max-w-2xl">
                Faelligkeiten ueber Wartungspflichten, Policen, Vertraege und Beschluesse aus allen verwalteten Objekten.
                Karten lassen sich per Drag &amp; Drop in andere Bucket schieben — z.B. um eine Vertrags­verlaengerung
                manuell als „erledigt“ zu markieren oder einen ueberfaelligen Eintrag in „in 30 Tagen“ zu vertagen
                (mit Begruendung im Audit-Log, hier nicht persistiert).
              </p>
            </div>
            <div className="flex items-stretch gap-3 shrink-0">
              <KpiTile label="überfällig" value={totals.overdue} tone="danger" hint="sofort handeln" />
              <KpiTile label="Objekte betroffen" value={totals.objects} tone="neutral" hint={`von ${objectsForFilter.length}`} />
              <KpiTile label="Volumen offen" value={fmtEUR(totals.impactValue)} tone="info" hint="aus Policen + Beschluessen" mono />
            </div>
          </div>

          {/* Filters */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="section-eyebrow mr-1">Filter</span>
            <FilterDropdown label="Objekt" value={filter.object} onChange={v => setFilter(f => ({ ...f, object: v as any }))}
              options={[{ value: 'all', label: 'Alle Objekte', sub: `${objectsForFilter.length}` }, ...objectsForFilter.map(o => ({ value: o.code, label: o.code, sub: o.name }))]} />
            <FilterDropdown label="Typ" value={filter.kind} onChange={v => setFilter(f => ({ ...f, kind: v as any }))}
              options={[{ value: 'all', label: 'Alle Typen', sub: '' }, ...(Object.keys(kindLabels) as ItemKind[]).map(k => ({ value: k, label: kindLabels[k], sub: '' }))]} />
            <FilterDropdown label="Verantwortlich" value={filter.responsible} onChange={v => setFilter(f => ({ ...f, responsible: v as any }))}
              options={[{ value: 'all', label: 'Alle', sub: '' }, ...responsibles.map(([initials, name]) => ({ value: initials, label: initials, sub: name }))]} />

            {(filter.object !== 'all' || filter.kind !== 'all' || filter.responsible !== 'all') && (
              <button
                onClick={() => setFilter({ object: 'all', kind: 'all', responsible: 'all' })}
                className="text-[10px] font-mono uppercase tracking-wider text-[var(--accent)] hover:underline ml-2"
              >
                × Filter zurücksetzen
              </button>
            )}

            <div className="ml-auto flex items-stretch border border-[var(--border)] bg-[var(--surface-1)]">
              <ViewSwitch active>Kanban</ViewSwitch>
              <ViewSwitch>Liste</ViewSwitch>
              <ViewSwitch>Kalender</ViewSwitch>
              <ViewSwitch>Heatmap</ViewSwitch>
            </div>
            <button className="btn">Snooze ▸</button>
            <button className="btn btn-primary">+ Neuer Eintrag</button>
          </div>
        </div>
      </header>

      <main className="px-7 py-6 flex gap-6 min-w-0">
        <DndContext sensors={sensors} collisionDetection={closestCorners} onDragStart={onDragStart} onDragEnd={onDragEnd}>
          <div className="flex-1 min-w-0 overflow-x-auto">
            <div className="flex gap-3 pb-6" style={{ minWidth: 'fit-content' }}>
              {counts.map((b) => (
                <Column
                  key={b.id}
                  bucket={b.id}
                  label={b.label}
                  sub={b.sub}
                  tone={b.tone}
                  count={b.count}
                  totalCount={b.totalCount}
                  items={byBucket[b.id]}
                  onSelect={setSelectedId}
                  selectedId={selectedId}
                />
              ))}
            </div>
          </div>

          <DragOverlay dropAnimation={null}>
            {activeItem ? <Card item={activeItem} dragging /> : null}
          </DragOverlay>
        </DndContext>

        {selectedItem && (
          <DetailDrawer item={selectedItem} onClose={() => setSelectedId(null)} />
        )}
      </main>
    </>
  )
}

/* ──────────────────── Column ──────────────────── */

function Column({
  bucket, label, sub, tone, count, totalCount, items, onSelect, selectedId,
}: {
  bucket: Bucket; label: string; sub: string;
  tone: 'danger' | 'warn' | 'neutral' | 'info' | 'ok';
  count: number; totalCount: number;
  items: DueItem[];
  onSelect: (id: string) => void; selectedId: string | null;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `col-${bucket}` })

  const toneColor = tone === 'danger' ? 'var(--danger)' : tone === 'warn' ? 'var(--warn)' : tone === 'ok' ? 'var(--ok)' : tone === 'info' ? 'var(--info)' : 'var(--text-3)'

  return (
    <div
      ref={setNodeRef}
      className={`flex flex-col w-[300px] shrink-0 bg-[var(--surface-1)] border ${isOver ? 'border-[var(--accent)]' : 'border-[var(--border)]'} transition-colors`}
    >
      {/* Column header */}
      <div className="px-3 py-3 border-b border-[var(--hairline)] sticky top-0 bg-[var(--surface-1)] z-10">
        <div className="flex items-baseline justify-between gap-2 mb-1">
          <div className="flex items-baseline gap-2">
            <span className="block w-1.5 h-3" style={{ background: toneColor }} />
            <span className="text-[11px] font-medium text-[var(--text-1)] uppercase tracking-wider">{label}</span>
          </div>
          <div className="flex items-baseline gap-1">
            <span className="font-mono text-[15px] font-medium tabular text-[var(--text-1)]">{count}</span>
            {count !== totalCount && (
              <span className="font-mono text-[10px] tabular text-[var(--text-4)]">/{totalCount}</span>
            )}
          </div>
        </div>
        <div className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-3)]">{sub}</div>
      </div>

      {/* Cards list */}
      <SortableContext items={items.map(i => i.id)} strategy={verticalListSortingStrategy}>
        <div className="flex-1 px-2 py-2 space-y-2 min-h-[200px] overflow-y-auto" style={{ maxHeight: 'calc(100vh - 290px)' }}>
          {items.map(it => (
            <SortableCard key={it.id} item={it} onSelect={onSelect} selected={selectedId === it.id} />
          ))}
          {items.length === 0 && (
            <div className="border border-dashed border-[var(--hairline)] py-8 text-center text-[10px] font-mono uppercase tracking-wider text-[var(--text-4)]">
              — leer
            </div>
          )}
        </div>
      </SortableContext>
    </div>
  )
}

/* ──────────────────── Sortable Card ──────────────────── */

function SortableCard({ item, onSelect, selected }: { item: DueItem; onSelect: (id: string) => void; selected: boolean }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: item.id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  }

  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners}>
      <Card item={item} onClick={() => onSelect(item.id)} selected={selected} />
    </div>
  )
}

/* ──────────────────── Card ──────────────────── */

function Card({ item, dragging, onClick, selected }: { item: DueItem; dragging?: boolean; onClick?: () => void; selected?: boolean }) {
  const overdue = item.daysDelta < 0
  const soon = item.daysDelta >= 0 && item.daysDelta <= 30
  const statusColor = overdue ? 'var(--danger)' : soon ? 'var(--warn)' : item.daysDelta <= 90 ? 'var(--text-2)' : item.daysDelta <= 180 ? 'var(--info)' : 'var(--ok)'

  return (
    <div
      onClick={onClick}
      className={`relative bg-[var(--bg)] border transition-all p-3 cursor-grab active:cursor-grabbing
        ${selected ? 'border-[var(--accent)] shadow-[inset_0_0_0_1px_var(--accent)]' : 'border-[var(--border)] hover:border-[var(--border-2)]'}
        ${dragging ? 'shadow-2xl rotate-[1.2deg]' : ''}
      `}
    >
      {item.pinned && (
        <span className="absolute top-1 right-1 w-1.5 h-1.5 bg-[var(--accent)]" title="Angepinnt" />
      )}

      {/* Header line */}
      <div className="flex items-center justify-between gap-2 mb-1.5">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="font-mono text-[10px] tabular text-[var(--accent)] shrink-0">{item.objectCode}</span>
          <span className="text-[10px] text-[var(--text-3)] truncate">{item.objectName}</span>
        </div>
        <span className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-4)] shrink-0" title={kindLabels[item.kind]}>
          <span className="text-[var(--text-2)] mr-1">{kindGlyph[item.kind]}</span>
          {kindLabels[item.kind]}
        </span>
      </div>

      {/* Title */}
      <div className="text-[13px] leading-tight text-[var(--text-1)] font-medium mb-1.5">{item.title}</div>

      {/* Detail */}
      <div className="text-[11px] text-[var(--text-3)] leading-snug mb-3 truncate">{item.detail}</div>

      {/* Footer */}
      <div className="flex items-center justify-between pt-2 border-t border-[var(--hairline)] gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <Avatar initials={item.responsibleInitials} size={20} type="person" />
          <span className="text-[10px] font-mono text-[var(--text-3)] truncate">{item.responsible}</span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {item.amount !== undefined && (
            <span className="font-mono text-[10px] tabular text-[var(--text-2)]">
              {item.amount.toLocaleString('de-DE')} €
            </span>
          )}
          <span className="font-mono text-[11px] tabular tracking-tight" style={{ color: statusColor }}>
            {overdue ? `+${Math.abs(item.daysDelta)}d über` : `${item.daysDelta}d`}
          </span>
        </div>
      </div>
    </div>
  )
}

/* ──────────────────── KPI Tile ──────────────────── */

function KpiTile({ label, value, tone, hint, mono }: {
  label: string; value: string | number;
  tone: 'danger' | 'warn' | 'info' | 'neutral' | 'ok';
  hint: string; mono?: boolean
}) {
  const color = tone === 'danger' ? 'var(--danger)' : tone === 'warn' ? 'var(--warn)' : tone === 'info' ? 'var(--info)' : tone === 'ok' ? 'var(--ok)' : 'var(--text-1)'
  return (
    <div className="border border-[var(--border)] px-3 py-2 bg-[var(--surface-1)] min-w-[120px]">
      <div className="text-[9px] font-mono uppercase tracking-[0.18em] text-[var(--text-3)]">{label}</div>
      <div className={`mt-0.5 font-medium leading-none ${mono ? 'font-mono tabular text-base' : 'text-[24px]'}`} style={{ color }}>
        {value}
      </div>
      <div className="text-[9px] font-mono uppercase tracking-wider text-[var(--text-4)] mt-1">{hint}</div>
    </div>
  )
}

/* ──────────────────── Filter Dropdown ──────────────────── */

function FilterDropdown({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void;
  options: { value: string; label: string; sub: string }[]
}) {
  const [open, setOpen] = useState(false)
  const selected = options.find(o => o.value === value)

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className={`flex items-center gap-2 px-2.5 py-1.5 border text-[10px] font-mono uppercase tracking-wider transition-colors ${
          value !== 'all'
            ? 'bg-[var(--accent-bg)] border-[var(--accent-line)] text-[var(--accent)]'
            : 'bg-[var(--surface-1)] border-[var(--border)] text-[var(--text-2)] hover:border-[var(--border-2)] hover:text-[var(--text-1)]'
        }`}
      >
        <span className="text-[var(--text-3)]">{label}</span>
        <span>{selected?.label || 'Alle'}</span>
        <span className="text-[var(--text-4)]">▾</span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute z-20 top-full left-0 mt-1 min-w-[200px] max-h-[360px] overflow-y-auto bg-[var(--surface-1)] border border-[var(--border-2)] shadow-2xl">
            {options.map(o => (
              <button
                key={o.value}
                onClick={() => { onChange(o.value); setOpen(false) }}
                className={`w-full flex items-baseline justify-between gap-3 px-3 py-1.5 text-xs text-left hover:bg-[var(--surface-2)] transition-colors border-b border-[var(--hairline)] last:border-0 ${o.value === value ? 'bg-[var(--accent-bg)] text-[var(--accent)]' : 'text-[var(--text-1)]'}`}
              >
                <span className="font-mono">{o.label}</span>
                {o.sub && <span className="text-[10px] font-mono text-[var(--text-3)] truncate">{o.sub}</span>}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function ViewSwitch({ children, active }: { children: React.ReactNode; active?: boolean }) {
  return (
    <button
      disabled={!active}
      className={`px-2.5 py-1.5 text-[10px] uppercase tracking-[0.16em] font-mono transition-colors border-r border-[var(--border)] last:border-r-0 ${
        active ? 'bg-[var(--accent)] text-[var(--bg)]' : 'text-[var(--text-3)] cursor-not-allowed'
      }`}
    >
      {children}
    </button>
  )
}

/* ──────────────────── Detail Drawer ──────────────────── */

function DetailDrawer({ item, onClose }: { item: DueItem; onClose: () => void }) {
  const overdue = item.daysDelta < 0
  return (
    <aside className="w-[360px] shrink-0 border border-[var(--border)] bg-[var(--surface-1)] self-start sticky top-[140px] flex flex-col max-h-[calc(100vh-160px)] fade-up">
      <header className="px-5 pt-4 pb-3 border-b border-[var(--border)]">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="font-mono text-[10px] uppercase tracking-wider text-[var(--accent)]">{item.objectCode}</span>
              <span className="text-[10px] text-[var(--text-3)] truncate">{item.objectName}</span>
            </div>
            <h3 className="font-display text-[18px] italic font-light leading-tight">{item.title}</h3>
          </div>
          <button onClick={onClose} className="text-[var(--text-3)] hover:text-[var(--text-1)] text-lg leading-none p-1">×</button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-5 space-y-4">
        {/* Status block */}
        <div className={`p-3 border ${overdue ? 'border-[var(--danger-line)] bg-[var(--danger-bg)]' : 'border-[var(--border)]'}`}>
          <div className="text-[10px] uppercase tracking-wider text-[var(--text-3)] mb-1">Faelligkeit</div>
          <div className="font-mono tabular text-base">{item.dueDate}</div>
          <div className={`text-xs font-mono tabular mt-1 ${overdue ? 'text-[var(--danger)]' : 'text-[var(--text-2)]'}`}>
            {overdue ? `${Math.abs(item.daysDelta)} Tage überfällig` : `in ${item.daysDelta} Tagen`}
          </div>
        </div>

        {/* Detail */}
        <Field label="Typ" value={kindLabels[item.kind]} />
        <Field label="Beschreibung" value={item.detail} />
        {item.provider && <Field label="Anbieter" value={item.provider} />}
        {item.amount && <Field label="Volumen" value={fmtEUR(item.amount)} mono />}
        <Field label="Verantwortlich" value={
          <div className="flex items-center gap-2">
            <Avatar initials={item.responsibleInitials} type="person" size={22} />
            <span>{item.responsible}</span>
          </div>
        } />

        {/* Audit / actions placeholder */}
        <div className="pt-3 mt-3 border-t border-[var(--hairline)]">
          <div className="text-[10px] uppercase tracking-wider text-[var(--text-3)] mb-2">Audit-Trail</div>
          <ul className="space-y-1.5 text-[11px] font-mono text-[var(--text-3)]">
            <li>2026-04-28 · Eintrag aus Mirror erkannt</li>
            <li>2026-04-19 · Manuelle Notiz hinzugefügt</li>
            <li>2026-03-12 · Soll-Termin verstrichen</li>
          </ul>
        </div>
      </div>

      <footer className="px-4 py-3 border-t border-[var(--border)] bg-[var(--bg)] grid grid-cols-3 gap-1">
        <button className="btn !text-[9px] !py-1.5">Snooze 7 d</button>
        <button className="btn !text-[9px] !py-1.5">Zu Steckbrief</button>
        <button className="btn btn-primary !text-[9px] !py-1.5">Erledigen</button>
      </footer>
    </aside>
  )
}

function Field({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-[var(--text-3)] mb-0.5">{label}</div>
      <div className={`text-sm text-[var(--text-1)] ${mono ? 'font-mono tabular' : ''}`}>{value}</div>
    </div>
  )
}
