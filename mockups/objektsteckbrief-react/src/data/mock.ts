// Mock-Daten fuer HAM61 — WEG Eppendorfer Landstrasse 47-49, Hamburg
// Realistisch, aber rein illustrativ. Keine echten Personen / Bankdaten.

export type Provenance = 'manual' | 'mirror' | 'ai' | 'derived' | 'missing'

export const objekt = {
  shortCode: 'HAM61',
  name: 'WEG Eppendorfer Landstraße 47–49',
  city: '20251 Hamburg',
  district: 'Hamburg-Eppendorf',
  street: 'Eppendorfer Landstraße 47–49',
  country: 'Deutschland',
  wegNumberIntern: 'HAM-2007-061',
  impowerId: 'prop_8a3f9c12',
  facilioId: '71402',
  yearBuilt: 1924,
  unitCount: 14,
  buildings: 2,
  totalMea: '1.000,00 / 1.000,00',
  pflegegrad: 76,
  pflegegradDelta: 4,
  reviewQueueCount: 12,
}

export const owners = [
  { initials: 'DK', name: 'Kroll Beteiligung GmbH', mea: '342,5', stimmen: 4, type: 'firm' as const, notes: 'Mehrheit · zahlt zuverlaessig · Beirat' },
  { initials: 'MS', name: 'Marlene Sievertsen', mea: '187,2', stimmen: 2, type: 'person' as const, notes: 'Beirat · kritisch bei Sanierungs-Beschluessen' },
  { initials: 'AT', name: 'Andreas Thode', mea: '142,8', stimmen: 2, type: 'person' as const, notes: 'Auslaender · alle Schreiben in EN' },
  { initials: 'HK', name: 'Hauck & Krause GbR', mea: '128,4', stimmen: 2, type: 'firm' as const, notes: '' },
  { initials: 'BS', name: 'Birgit Schoene', mea:  '98,6', stimmen: 1, type: 'person' as const, notes: '' },
  { initials: 'JM', name: 'Jens Marqu., Erbengem.', mea: '100,5', stimmen: 3, type: 'firm' as const, notes: 'Erbengemeinschaft · Vollmacht bei Notar Bohrmann' },
]

export const accounts = [
  {
    purpose: 'WEG-Konto',
    bank: 'Hamburger Sparkasse',
    iban: 'DE12 2005 0550 1000 2398 11',
    balance: 48_722.30,
    deltaToday: 1_240.00,
    sparkline: [42_100, 42_810, 43_200, 44_800, 47_100, 46_200, 45_900, 47_400, 48_100, 48_400, 48_650, 48_722],
    live: true,
  },
  {
    purpose: 'Instandhaltungs-Rücklage',
    bank: 'Hamburger Sparkasse',
    iban: 'DE38 2005 0550 1000 2398 22',
    balance: 218_540.55,
    deltaToday: 0,
    sparkline: [180_400, 184_200, 188_100, 192_300, 196_800, 201_200, 205_700, 209_900, 213_100, 215_800, 217_400, 218_540],
    live: true,
  },
  {
    purpose: 'Mietkonto Sondereig.',
    bank: 'Volksbank Hamburg',
    iban: 'DE89 2019 0003 0084 5710 00',
    balance: 12_310.00,
    deltaToday: 480.00,
    sparkline: [11_200, 11_640, 11_580, 11_900, 11_820, 12_050, 12_180, 12_240, 12_140, 12_220, 12_310, 12_310],
    live: false,
  },
]

export const finance = {
  reserveTargetMonthly: 4_200,
  reserveCurrent: 218_540.55,
  paymentQuotaPct: 94.2,
  wirtschaftsplanStatus: { label: 'beschlossen 12.11.2025', state: 'ok' as const },
  jahresabrechnungStatus: { label: 'Erstellung lauft', state: 'warn' as const },
  sonderumlagen: [
    { date: '2024-04', titel: 'Fassaden-Anstrich Hofseite', amount: 38_500, paid: 38_500, status: 'abgeschlossen' },
    { date: '2026-09', titel: 'Geplant: Heizung Modernisierung', amount: 145_000, paid: 0, status: 'beschluss-vorgesehen' },
  ],
}

export const technik = {
  shutoffs: [
    { kind: 'Wasser', location: 'Keller Haus 47, Raum links neben Treppe', photoStatus: 'present' as const, lastVerified: '2025-08-14' },
    { kind: 'Gas',    location: 'Hofseite Haus 49, externer Schacht',      photoStatus: 'missing' as const, lastVerified: '—' },
    { kind: 'Strom',  location: 'Hauptverteilung Keller Haus 49',          photoStatus: 'present' as const, lastVerified: '2025-11-02' },
  ],
  heating: {
    type: 'Gas-Brennwert',
    manufacturer: 'Viessmann Vitocrossal 200',
    yearInstalled: 2014,
    serviceProvider: 'Heizungsbau Mertens GmbH',
    serviceProviderId: 'svc_mertens_gmbh',
    faultHotline: '040 / 31 88 24 – 0',
    location: 'Heizungsraum Keller Haus 47',
  },
  accessCodes: [
    { label: 'Haustur Haus 47',   value: '••••', encrypted: true },
    { label: 'Haustur Haus 49',   value: '••••', encrypted: true },
    { label: 'Tiefgarage',        value: 'kein TG', encrypted: false },
  ],
  history: [
    { year: 1924, label: 'Errichtung',                kind: 'origin'   as const },
    { year: 1998, label: 'Gesamtsanierung',           kind: 'major'    as const },
    { year: 1998, label: 'Leitungen Wasser',          kind: 'minor'    as const },
    { year: 2008, label: 'Dach',                       kind: 'minor'    as const },
    { year: 2008, label: 'Fassade',                    kind: 'minor'    as const },
    { year: 2014, label: 'Heizung',                    kind: 'minor'    as const },
    { year: 2014, label: 'Fenster (87 %)',             kind: 'minor'    as const },
    { year: 2026, label: 'Heizung-Modernisierung (geplant)', kind: 'planned' as const },
  ],
}

export const policies = [
  {
    insurer: 'Allianz',  insurerInitial: 'A',
    type: 'Gebäudeversicherung',
    number: 'AVB-22 / 4 098 771',
    sum: '8.400.000,00 €',
    deductible: 1_500,
    premium: 6_842.50,
    end: '2026-06-14',
    daysToEnd: 47,
    holder: 'WEG',
    risk: 'high' as const,
  },
  {
    insurer: 'VHV',      insurerInitial: 'V',
    type: 'Haus- & Grund-Haftpflicht',
    number: 'HG-7710 / 184 220',
    sum: '10.000.000,00 €',
    deductible: 250,
    premium: 982.00,
    end: '2027-01-31',
    daysToEnd: 278,
    holder: 'WEG',
    risk: 'low' as const,
  },
  {
    insurer: 'Domcura',  insurerInitial: 'D',
    type: 'Glasversicherung',
    number: 'GL-114 / 220 188',
    sum: 'Pauschal',
    deductible: 0,
    premium: 318.00,
    end: '2027-04-01',
    daysToEnd: 338,
    holder: 'WEG',
    risk: 'low' as const,
  },
  {
    insurer: 'Allianz',  insurerInitial: 'A',
    type: 'Elementar (Zusatz)',
    number: 'EL-22 / 4 098 771',
    sum: '8.400.000,00 €',
    deductible: 5_000,
    premium: 1_120.00,
    end: '2026-06-14',
    daysToEnd: 47,
    holder: 'WEG',
    risk: 'med' as const,
  },
]

export const obligations = [
  { type: 'Heizungswartung',     last: '2025-11-04', next: '2026-11-04', status: 'ok' as const,       provider: 'Mertens' },
  { type: 'Aufzug-TÜV',          last: '2024-09-12', next: '2026-03-12', status: 'overdue' as const,  provider: 'TÜV Nord', overdueBy: 47 },
  { type: 'Trinkwasserprüfung',  last: '2024-12-18', next: '2026-06-22', status: 'soon' as const,     provider: 'Wessling',  daysTo: 60 },
  { type: 'Schornsteinfeger',    last: '2025-07-08', next: '2027-07-08', status: 'ok' as const,       provider: 'Bezirk Eppendorf' },
  { type: 'Rückstausicherung',   last: '—',          next: '—',          status: 'unknown' as const,  provider: '—' },
]

export const damages = [
  { date: '2024-11-08', type: 'Leitungswasser',  unit: 'WE 4',  claim: 18_400, settled: 16_200, status: 'reguliert' as const, ref: 'AVB-S-2024-1142' },
  { date: '2024-04-22', type: 'Sturm',           unit: 'Dach',  claim:  4_300, settled:  4_300, status: 'reguliert' as const, ref: 'AVB-S-2024-0418' },
  { date: '2023-12-19', type: 'Glasbruch',       unit: 'WE 11', claim:    640, settled:    640, status: 'reguliert' as const, ref: 'GL-2023-220' },
  { date: '2023-08-04', type: 'Leitungswasser',  unit: 'WE 7',  claim: 22_000, settled:      0, status: 'abgelehnt' as const, ref: 'AVB-S-2023-0918' },
  { date: '2022-10-30', type: 'Elementar (Hochwasser)', unit: 'Keller', claim: 11_900, settled: 9_400, status: 'reguliert' as const, ref: 'EL-2022-0341' },
]

export const dueRadar = [
  { kind: 'overdue' as const, label: 'Aufzug-TÜV',          since: 47,  unit: 'Tage überfällig' },
  { kind: 'soon'    as const, label: 'Allianz Gebäude',     in: 47,    unit: 'Tage bis Ablauf' },
  { kind: 'soon'    as const, label: 'Trinkwasserprüfung',  in: 60,    unit: 'Tage bis Fälligkeit' },
]

export const reviewQueue = [
  {
    id: 'q-1', target: 'technik.heating.yearInstalled', label: 'Heizungs-Baujahr',
    proposal: '2014', current: '2013',
    confidence: 0.92,
    source: 'pdf' as const, sourceLabel: 'Wartungsprotokoll Mertens 2024.pdf',
    age: 'vor 2 h',
  },
  {
    id: 'q-2', target: 'policies[Allianz/Gebäude].next_main_due', label: 'Police Hauptfälligkeit',
    proposal: '14.06.2026', current: '01.07.2026',
    confidence: 0.88,
    source: 'pdf' as const, sourceLabel: 'Allianz Versicherungsschein 2024.pdf',
    age: 'vor 5 h',
  },
  {
    id: 'q-3', target: 'cluster9.te_structured.special_usage_rights', label: 'Sondernutzungsrecht Garten',
    proposal: 'WE 3 — Vorgarten Hofseite, vermessen 1998',
    current: '—',
    confidence: 0.71,
    source: 'pdf' as const, sourceLabel: 'Teilungserklärung 1998.pdf · Seite 14',
    age: 'gestern',
  },
  {
    id: 'q-4', target: 'finance.special_contributions', label: 'Sonderumlage 2026 Heizung',
    proposal: '145.000,00 €',
    current: '—',
    confidence: 0.86,
    source: 'chat' as const, sourceLabel: 'Chat-Verlauf · Daniel Kroll',
    age: 'gestern',
  },
  {
    id: 'q-5', target: 'cluster10.energy_certificate', label: 'Energieausweis Endenergie',
    proposal: '142 kWh/(m²·a) · Klasse E · gültig bis 2031-04-12',
    current: '—',
    confidence: 0.94,
    source: 'mirror' as const, sourceLabel: 'Impower Property-Mirror',
    age: 'heute, 02:31',
  },
]

export const units = [
  { nr: 'WE 1',  type: 'Wohnung', sqm: 78.4,  rooms: 2.5, floor: 'EG-li',  tenant: 'Voigt, S.',     status: 'vermietet' },
  { nr: 'WE 2',  type: 'Wohnung', sqm: 92.1,  rooms: 3.0, floor: 'EG-re',  tenant: '— Eigentum',     status: 'eigengenutzt' },
  { nr: 'WE 11', type: 'Gewerbe', sqm: 41.2,  rooms: 1.0, floor: '4.OG',   tenant: 'Kanzlei Bredow', status: 'vermietet' },
]

// Provenance distribution per section, used in sidebar bars
export const sectionProvenance = {
  stammdaten:     { manual: 2,  mirror: 8, ai: 0, missing: 0 },
  einheiten:      { manual: 6,  mirror: 14, ai: 0, missing: 2 },
  personen:       { manual: 4,  mirror: 18, ai: 0, missing: 0 },
  technik:        { manual: 11, mirror: 0, ai: 2, missing: 3 },
  medien:         { manual: 18, mirror: 0, ai: 0, missing: 14 },
  finanzen:       { manual: 1,  mirror: 22, ai: 1, missing: 0 },
  vertrag:        { manual: 9,  mirror: 0, ai: 0, missing: 1 },
  versicherungen: { manual: 14, mirror: 0, ai: 4, missing: 1 },
  recht:          { manual: 3,  mirror: 11, ai: 2, missing: 8 },
  baurecht:       { manual: 6,  mirror: 0, ai: 1, missing: 11 },
}

export type SectionKey = keyof typeof sectionProvenance
