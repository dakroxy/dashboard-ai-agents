// Due-Radar Mock-Daten — querschnitt ueber 8 Objekte
// Spalten = Faelligkeits-Buckets in Tagen ab heute (28.04.2026)

export type Bucket = 'overdue' | 'd30' | 'd60' | 'd90' | 'd180' | 'ok'

export type ItemKind = 'wartung' | 'police' | 'vertrag' | 'beschluss' | 'pruefung'

export interface DueItem {
  id: string
  bucket: Bucket
  kind: ItemKind
  objectCode: string
  objectName: string
  title: string
  detail: string
  dueDate: string
  daysDelta: number     // negative = ueberfaellig, positive = in Zukunft
  amount?: number       // EUR (Vertraege, Policen)
  responsible: string
  responsibleInitials: string
  provider?: string
  pinned?: boolean
}

export const buckets: { id: Bucket; label: string; sub: string; tone: 'danger' | 'warn' | 'neutral' | 'info' | 'ok' }[] = [
  { id: 'overdue', label: 'Überfällig',     sub: 'sofort handeln',           tone: 'danger' },
  { id: 'd30',     label: 'In 30 Tagen',    sub: '— akut',                    tone: 'warn' },
  { id: 'd60',     label: 'In 31–60 Tagen', sub: 'planen',                    tone: 'warn' },
  { id: 'd90',     label: 'In 61–90 Tagen', sub: 'vorbereiten',               tone: 'neutral' },
  { id: 'd180',    label: 'In 91–180 Tagen', sub: 'beobachten',               tone: 'info' },
  { id: 'ok',      label: 'OK · > 180 d',   sub: 'frisch erledigt / weit weg', tone: 'ok' },
]

export const objectsForFilter = [
  { code: 'HAM61', name: 'WEG Eppendorfer Landstr. 47–49' },
  { code: 'HAM58', name: 'WEG Mittelweg 142' },
  { code: 'HAM63', name: 'MV Sierichstr. 88' },
  { code: 'HAM64', name: 'MV Hofweg 14a' },
  { code: 'BRE11', name: 'WEG Vahrer Str. 220, Bremen' },
  { code: 'GVE1',  name: 'WEG Gartenstr. 7, Buxtehude' },
  { code: 'HAM72', name: 'WEG Lehmweg 31' },
  { code: 'HAM55', name: 'WEG Klosterallee 90' },
]

export const dueItems: DueItem[] = [
  // ÜBERFÄLLIG
  { id: 'i-01', bucket: 'overdue', kind: 'wartung', objectCode: 'HAM61', objectName: 'Eppendorfer L.', title: 'Aufzug-TÜV', detail: 'Letzte Prüfung 2024-09-12', dueDate: '2026-03-12', daysDelta: -47, responsible: 'D. Kroll', responsibleInitials: 'DK', provider: 'TÜV Nord', pinned: true },
  { id: 'i-02', bucket: 'overdue', kind: 'pruefung', objectCode: 'HAM58', objectName: 'Mittelweg 142', title: 'Trinkwasserprüfung', detail: 'Lt. UBA-Vorgabe 2-jährlich', dueDate: '2026-04-08', daysDelta: -20, responsible: 'M. Bauer', responsibleInitials: 'MB', provider: 'Wessling Labor' },
  { id: 'i-03', bucket: 'overdue', kind: 'beschluss', objectCode: 'HAM72', objectName: 'Lehmweg 31', title: 'Beschluss-Umsetzung Hofbegrünung', detail: 'ETV 2025-09-12 · noch nicht beauftragt', dueDate: '2026-03-31', daysDelta: -28, responsible: 'D. Kroll', responsibleInitials: 'DK' },

  // ≤ 30 Tage
  { id: 'i-04', bucket: 'd30', kind: 'police', objectCode: 'HAM61', objectName: 'Eppendorfer L.', title: 'Allianz Gebäude­versicherung', detail: 'Hauptfälligkeit · 6.842 € p.a.', dueDate: '2026-06-14', daysDelta: 47, amount: 6842, responsible: 'D. Kroll', responsibleInitials: 'DK', provider: 'Allianz' },
  { id: 'i-05', bucket: 'd30', kind: 'police', objectCode: 'HAM61', objectName: 'Eppendorfer L.', title: 'Allianz Elementar (Zusatz)', detail: '1.120 € p.a.', dueDate: '2026-06-14', daysDelta: 47, amount: 1120, responsible: 'D. Kroll', responsibleInitials: 'DK', provider: 'Allianz' },
  { id: 'i-06', bucket: 'd30', kind: 'wartung', objectCode: 'HAM63', objectName: 'Sierichstr. 88', title: 'Schornsteinfeger-Pflicht', detail: 'Bezirk Eppendorf · 1× p.a.', dueDate: '2026-05-22', daysDelta: 24, responsible: 'M. Bauer', responsibleInitials: 'MB', provider: 'Bezirks-Schornsteinfeger' },
  { id: 'i-07', bucket: 'd30', kind: 'vertrag', objectCode: 'GVE1',  objectName: 'Gartenstr. 7', title: 'Verwaltervertrag · Preis-Review', detail: 'lt. Vertrag § 6 alle 3 Jahre', dueDate: '2026-05-31', daysDelta: 33, responsible: 'D. Kroll', responsibleInitials: 'DK' },
  { id: 'i-08', bucket: 'd30', kind: 'pruefung', objectCode: 'BRE11', objectName: 'Vahrer Str. 220', title: 'Aufzug-TÜV (kleiner)', detail: 'Personenaufzug Haus 2 · alle 2J', dueDate: '2026-05-12', daysDelta: 14, responsible: 'M. Bauer', responsibleInitials: 'MB', provider: 'TÜV Nord' },

  // ≤ 60 Tage
  { id: 'i-09', bucket: 'd60', kind: 'pruefung', objectCode: 'HAM61', objectName: 'Eppendorfer L.', title: 'Trinkwasserprüfung', detail: 'Wessling · gem. TrinkwV', dueDate: '2026-06-22', daysDelta: 60, responsible: 'M. Bauer', responsibleInitials: 'MB', provider: 'Wessling Labor' },
  { id: 'i-10', bucket: 'd60', kind: 'wartung', objectCode: 'HAM55', objectName: 'Klosterallee 90', title: 'Heizungs-Wartung', detail: 'Mertens · jährlich', dueDate: '2026-06-15', daysDelta: 53, responsible: 'M. Bauer', responsibleInitials: 'MB', provider: 'Mertens GmbH' },
  { id: 'i-11', bucket: 'd60', kind: 'police', objectCode: 'HAM58', objectName: 'Mittelweg 142', title: 'Domcura Glasversicherung', detail: '218 € p.a.', dueDate: '2026-06-30', daysDelta: 63, amount: 218, responsible: 'D. Kroll', responsibleInitials: 'DK', provider: 'Domcura' },
  { id: 'i-12', bucket: 'd60', kind: 'vertrag', objectCode: 'HAM72', objectName: 'Lehmweg 31', title: 'Hausmeister-Vertrag · Kündigungsfrist', detail: 'lt. Vertrag bis 30.06.', dueDate: '2026-06-30', daysDelta: 63, responsible: 'D. Kroll', responsibleInitials: 'DK', provider: 'Lange Hausmeisterservice' },

  // ≤ 90 Tage
  { id: 'i-13', bucket: 'd90', kind: 'beschluss', objectCode: 'HAM61', objectName: 'Eppendorfer L.', title: 'Sonderumlage Heizung 145 T€', detail: 'ETV 2026-06-12 vorgesehen', dueDate: '2026-06-12', daysDelta: 45, amount: 145000, responsible: 'D. Kroll', responsibleInitials: 'DK' },
  { id: 'i-14', bucket: 'd90', kind: 'wartung', objectCode: 'HAM63', objectName: 'Sierichstr. 88', title: 'Heizungs-Wartung', detail: 'jährlich · Mertens', dueDate: '2026-07-04', daysDelta: 67, responsible: 'M. Bauer', responsibleInitials: 'MB', provider: 'Mertens GmbH' },
  { id: 'i-15', bucket: 'd90', kind: 'pruefung', objectCode: 'HAM55', objectName: 'Klosterallee 90', title: 'Spielplatz-Prüfung', detail: 'DIN EN 1176 jährlich', dueDate: '2026-07-15', daysDelta: 78, responsible: 'M. Bauer', responsibleInitials: 'MB', provider: 'TÜV Süd' },
  { id: 'i-16', bucket: 'd90', kind: 'police', objectCode: 'HAM72', objectName: 'Lehmweg 31', title: 'VHV Haus & Grund Haftpflicht', detail: '982 € p.a.', dueDate: '2026-07-22', daysDelta: 85, amount: 982, responsible: 'D. Kroll', responsibleInitials: 'DK', provider: 'VHV' },

  // ≤ 180 Tage
  { id: 'i-17', bucket: 'd180', kind: 'wartung', objectCode: 'HAM64', objectName: 'Hofweg 14a', title: 'Rückstausicherung', detail: '2-jährig', dueDate: '2026-09-30', daysDelta: 155, responsible: 'M. Bauer', responsibleInitials: 'MB' },
  { id: 'i-18', bucket: 'd180', kind: 'beschluss', objectCode: 'HAM58', objectName: 'Mittelweg 142', title: 'Wirtschaftsplan 2027', detail: 'ETV 2026-10-07', dueDate: '2026-10-07', daysDelta: 162, responsible: 'D. Kroll', responsibleInitials: 'DK' },
  { id: 'i-19', bucket: 'd180', kind: 'police', objectCode: 'BRE11', objectName: 'Vahrer Str. 220', title: 'Gebäudeversicherung Provinzial', detail: '4.420 € p.a.', dueDate: '2026-10-15', daysDelta: 170, amount: 4420, responsible: 'D. Kroll', responsibleInitials: 'DK', provider: 'Provinzial' },
  { id: 'i-20', bucket: 'd180', kind: 'vertrag', objectCode: 'HAM55', objectName: 'Klosterallee 90', title: 'Reinigungsfirma · Vertragsende', detail: 'Verlaengerung pruefen', dueDate: '2026-10-31', daysDelta: 186, responsible: 'D. Kroll', responsibleInitials: 'DK', provider: 'Cleanline KG' },

  // OK
  { id: 'i-21', bucket: 'ok', kind: 'wartung', objectCode: 'HAM61', objectName: 'Eppendorfer L.', title: 'Heizungs-Wartung', detail: 'erledigt 2025-11-04 · nächste in 11 Mo', dueDate: '2026-11-04', daysDelta: 190, responsible: 'M. Bauer', responsibleInitials: 'MB', provider: 'Mertens GmbH' },
  { id: 'i-22', bucket: 'ok', kind: 'police', objectCode: 'HAM63', objectName: 'Sierichstr. 88', title: 'VHV Haftpflicht', detail: 'verlaengert 2026-01 · 24 Mo', dueDate: '2027-01-31', daysDelta: 278, amount: 1240, responsible: 'D. Kroll', responsibleInitials: 'DK', provider: 'VHV' },
  { id: 'i-23', bucket: 'ok', kind: 'pruefung', objectCode: 'HAM72', objectName: 'Lehmweg 31', title: 'Aufzug-TÜV', detail: 'erledigt 2025-11-22', dueDate: '2027-11-22', daysDelta: 573, responsible: 'M. Bauer', responsibleInitials: 'MB', provider: 'TÜV Nord' },
  { id: 'i-24', bucket: 'ok', kind: 'wartung', objectCode: 'GVE1', objectName: 'Gartenstr. 7', title: 'Schornsteinfeger', detail: 'erledigt 03/2026', dueDate: '2027-03-15', daysDelta: 321, responsible: 'M. Bauer', responsibleInitials: 'MB' },
]
