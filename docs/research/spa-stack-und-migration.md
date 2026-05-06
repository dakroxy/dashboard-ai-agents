# SPA-Stack und Migrations-Pattern — Technische Recherche

**Stand**: 2026-05-05
**Auftrag**: Foundation-Doku fuer das nachfolgende Architektur-Doc und die UX-Spec.
**Entscheidungen, die hier festgelegt werden**: Frontend-Stack, Migrations-Strategie, Auth-/Co-Existence-Modell.

## 0. Executive Summary

| Thema | Empfehlung | Kernbegruendung |
|---|---|---|
| **Frontend-Stack** | **Vite + React 18 + TanStack Router + TanStack Query** (CSR-only, kein SSR) | Internes B2B-Tool ohne SEO → SSR ist Overkill. Mockups laufen bereits exakt auf diesem Stack → 1:1 portierbar. End-to-end Type-safety ohne RSC-Magie. Kein Vendor-Lock-In. Upgrade-Pfad zu TanStack Start ist freiwillig, nicht erzwungen. |
| **Migrations-Pattern** | **Strangler-Fig pro Modul, Subpath-Mount unter `/app`** | Solo-Dev, laufende Produktion mit aktiven Modulen (SEPA, Mietverwaltung). Big-Bang ist Risiko-/Wertkurve negativ. Greenfield-Pilot waere ein neues Backend — hier nicht zutreffend. |
| **Auth + Co-Existence** | **Bestehende Cookie-Session (Authlib + Starlette `SessionMiddleware`) weiterverwenden, Double-Submit-CSRF fuer SPA-Mutationen** | Same-Origin (`dashboard.dbshome.de`) → kein CORS, kein JWT-Refresh-Tanz. HttpOnly-Cookie ist sicherer als localStorage-JWT. SPA + HTMX teilen sich denselben Auth-State. |

Verworfen werden Next.js (Lock-In, RSC-Komplexitaet, kein SEO-Bedarf), SvelteKit (Mockup-Reuse-Anforderung verletzt, schmaleres Ecosystem fuer Daten-dichte UIs), Remix als eigenstaendige Brand (existiert nicht mehr, in React Router 7 gemerged). React Router 7 Framework-Mode bleibt als naechstbeste Alternative — vergleichbar zu TanStack Router/Start, aber mit weniger Type-Safety im Routing.

---

## 1. Eingangslage

- **Backend**: FastAPI 0.115 + Postgres 16 + SQLAlchemy 2.0. Bleibt unveraendert. Battle-tested Domain-Logik (Impower-Connector, Claude-Integration, Mietverwaltungs-Pipeline) wird als JSON-API frontend-agnostisch.
- **Aktueller Frontend-Stack**: Jinja2 + HTMX 2 + Tailwind via CDN. Liefert Fragmente, keine JSON-API. Skaliert nicht in geforderte UX (Boards, Detail-Views mit hoher Datendichte, globaler Chat-Drawer, Cmd+K, Multi-Tab-Workflows).
- **Mockups**: Vite + React 18 + TS + Tailwind + @dnd-kit (`mockups/objektsteckbrief-react/package.json`). Hanseatic-Style steht. **Anforderung: 1:1-Portierung der Komponenten.**
- **Deployment**: Elestio Custom Docker Compose. Reverse-Proxy auf der VM ist Caddy-basiert (Elestio-default).
- **Auth**: Google Workspace OAuth via Authlib, Starlette `SessionMiddleware` mit `itsdangerous`-signiertem Cookie. Hard-Gate auf `@dbshome.de`. Permissions in DB (Rollen + ResourceAccess).
- **Solo-Dev** mit Claude Code als Kollaborator. Kein Team, kein Onboarding-Druck — aber jede Stunde, die in Stack-Komplexitaet flieesst, fehlt fuer Domain-Features.

---

## 2. Frontend-Stack

### 2.1 Auswahlkriterien

1. **Mockup-Reuse 1:1** — die zwei React-18-Inseln (Objektsteckbrief, Due-Radar Kanban) muessen ohne Rewrite uebernehmbar sein.
2. **Kein SEO-Bedarf** — alles hinter `@dbshome.de`-OAuth, kein oeffentlicher Index. SSR liefert hier keinen Mehrwert, nur Komplexitaet.
3. **Static-Hosting moeglich** — Caddy/Nginx vor FastAPI, Build-Output ist nur HTML+JS+CSS. Keine Node-Runtime in Prod.
4. **Lock-In-Risiko niedrig** — kein Framework-Hosting-Provider als impliziter Vertragspartner.
5. **Solo-Dev-DX** — schnelles HMR, lesbare Fehler, geringe Onboarding-Komplexitaet fuer Claude Code.
6. **Type-Safety end-to-end** — Router, Loader, Search-Params, API-Calls.
7. **Server-State-Strategie** — Caching, Background-Refetch, optimistic Updates ohne Eigenbau.
8. **Sustainability** — Maintainer-Modell, Funding, OSS-Health.

### 2.2 Verworfene Alternativen — knapp

#### Next.js (App Router)
- **Verwerfungsgrund**: Lock-In + RSC-Komplexitaet ohne Gegenwert.
- Self-Hosting moeglich, aber `next/image`, ISR-Persistenz, multi-instance Cache-Tag-Coordination, Connection-Pooling sind alles Themen, die auf Vercel "magisch" laufen und sich beim Self-Host als Eigenbau zeigen.
- App Router + RSC bringen Mental-Overhead (`"use client"`, Server Actions, Route-Cache, Data-Cache, Request-Memoization), die fuer ein Auth-only-Tool ohne SEO null Wert haben.
- Mockups muessten teilweise umgeschrieben werden: kein Vite, andere Routing-Konvention, RSC-Boundary-Annotation.
- Middleware-Bypass-CVE 2024 (CVE-2025-29927) zeigt, dass die Framework-Surface bei Self-Host extra Sorgfalt braucht.
- *Konkret: 14 % Marktanteil Vercel/Next.js bei B2B-internen Tools, aber dort meist mit Vercel-Hosting kombiniert.*

#### SvelteKit
- **Verwerfungsgrund**: Mockup-Reuse-Anforderung verletzt — alle bestehenden React-Komponenten waeren Wegwerf.
- Bundle-Vorteil real (~30 % weniger als React-Equivalent), aber irrelevant fuer ein Auth-only-Tool im Firmen-LAN/VPN.
- Daten-dichte B2B-Tools brauchen oft komplexe Drittanbieter-Komponenten (Charts, Date-Pickers, Tabellen mit Virtualization, DnD). React-Ecosystem ist hier deutlich tiefer; @dnd-kit-Aequivalent fuer Svelte ist `svelte-dnd-action` — funktioniert, aber kleinere Community.
- Hiring-Pool spielt fuer Solo-Dev keine Rolle, aber: Claude Code hat in React-Kontext mehr Trainings-Daten gesehen als in SvelteKit.

#### Remix (als eigenstaendige Brand)
- **Verwerfungsgrund**: existiert nicht mehr.
- Remix v3 wurde im November 2024 in React Router v7 gemerged. `@remix-run/*`-Pakete sind nun `react-router`. Wer Remix sagt, meint heute React Router 7 Framework-Mode.

#### TanStack Start (statt CSR-only Vite + TanStack Router)
- **Verwerfungsgrund**: derzeit nicht noetig, traegt SSR-Komplexitaet, die Wert-frei waere.
- TanStack Start hit v1.0 im Maerz 2026 — produktionstauglich, aber bringt SSR + Server-Functions, die wir fuer ein Auth-only-Tool ohne SEO nicht brauchen.
- **Wichtig**: TanStack Router (das wir nutzen) und TanStack Start sind *derselbe Router*. Ein Wechsel von "Vite + TanStack Router" auf "TanStack Start" spaeter ist ein additive Migration (man behaelt seinen Routing-Code), kein Stack-Bruch. Damit ist die heutige Entscheidung kein Sackgassen-Risiko.

### 2.3 Engere Auswahl — Trade-off-Tabelle

| Kriterium | **Vite + React + TanStack Router + Query** ⭐ | TanStack Start (RC v1) | React Router 7 Framework-Mode |
|---|---|---|---|
| Mockup-Reuse 1:1 | ✅ Identischer Stack | ✅ identisch (Router teilen) | 🟡 Routing-Konvention anders, Re-Wiring noetig |
| SSR/CSR | CSR-only (genau richtig) | CSR + optional SSR | SSR-default, CSR-opt-out moeglich |
| Type-Safety Routing | ✅ Compile-Time, Search-Params, Loaders typed | ✅ identisch | 🟡 Typed-Routes generated, weniger streng als TSR |
| Type-Safety Server-Actions | n/a (FastAPI ist Server) | typed Server-Functions | typed loader/action mit RR7 |
| Build-Tool | Vite (schnell, stabil) | Vite + TanStack-Plugin | Vite (RR7) |
| Static-Hosting | ✅ Trivial (Caddy `try_files`) | Braucht Node oder Adapter | Braucht Node oder Adapter |
| Vendor-Lock-In | Keiner | Keiner | Keiner |
| Lifetime/Sustainability | TanStack: 13 Projekte, 36 Maintainer, 16 Sponsoren ([Quelle](https://tanstack.com/blog/tanstack-2-years)) | gleich | React Router: long-term, von Remix-Team (Shopify) maintained |
| Server-State | TanStack Query (de-facto Standard) | identisch | identisch (extern) |
| Mental Model | Schmal — "React + Router + Query" | Mittel — Router + Server-Functions | Breit — Loader/Action/Form |
| Bundle-Footprint Router | TSR ~12 KB gz | identisch | RR7 ~14 KB gz |
| Risiko bei Stack-Aenderung | Klein — Migration zu TanStack Start ist additive | n/a | n/a |

### 2.4 Empfehlung: Vite + React 18 + TanStack Router + TanStack Query

#### Begruendung
- **CSR ist hier die richtige Wahl**, nicht eine Notloesung. Authenticated-Dashboard ohne SEO; SSR wuerde Build-/Deploy-Komplexitaet bringen ohne UX-Gewinn ([Quelle: AppMaster](https://appmaster.io/blog/ssr-vs-spa-authenticated-dashboards)).
- TanStack Router liefert das einzige in der React-Welt strikt Compile-Time-typisierte Routing — Search-Params, Path-Params, Loaders, alle typed. Tippfehler im Link werden Build-Errors, nicht 404s.
- Automatische Code-Splitting via TanStack-Vite-Plugin (`autoCodeSplitting: true`) — Initial-Bundle bleibt klein ([Quelle](https://tanstack.com/router/latest/docs/guide/automatic-code-splitting)).
- TanStack Query ist der De-facto-Standard fuer Server-State in React. Caching, Background-Refetch, Optimistic Updates, DevTools — fertig. Alles was wir aktuell mit HTMX-Polling (`hx-trigger="every 2s"`) und Meta-Refresh (`<meta http-equiv="refresh" content="6">`) bauen, wird mit `useQuery({refetchInterval: 2000})` 1-Liner.
- Sustainability: TanStack hat ein klares Funding-Modell (16 Sponsoren, voller Kern-Maintainer-Salary), ist nicht "Hobby-OSS" ([Quelle](https://tanstack.com/blog/tanstack-2-years)).
- Ecosystem-Faehigkeit: @dnd-kit, react-aria/react-spectrum, AG-Grid (falls Tabellen-Heavy), Recharts/Visx — alle React 18-kompatibel, sofort nutzbar.

#### Konkrete Mengenangaben
- **Bundle-Budget**: Initial-JS ≤ **180 KB gzipped** (Industrie-Best-Practice fuer mittlere SPAs liegt bei 50–150 KB; B2B-Dashboard mit DnD/Charts darf 150–200 sein). Total-JS bis ~600 KB akzeptabel, davon >70 % lazy-loaded ([Quelle](https://medium.com/@vasanthancomrads/performance-budgets-for-react-applications-7e796da09ef8)).
- **Build-Zeit**: Vite-Build fuer ein Projekt der erwarteten Groesse (~30 Routes, ~150 Komponenten) sollte unter 30 s lokal liegen. CI-Build inkl. typecheck + Test: 1.5–3 min realistisch.
- **HMR**: < 200 ms typischer Dev-Reload (Vite-Standard).

#### Type-Generation-Workflow
- **Empfehlung**: `@hey-api/openapi-ts` mit TanStack-Query-Plugin. Generiert SDK + Query-Hooks aus FastAPI-`/openapi.json` ([Quelle](https://heyapi.dev/openapi-ts/plugins/tanstack-query)).
- Lokal als `npm run gen:api` Skript, das `http://localhost:8000/openapi.json` zieht. CI generiert vor dem Build und failed bei Drift.
- Alternative: `openapi-typescript` + `openapi-fetch` + `openapi-react-query` (modularer, weniger Abstraktion). Nicht falsch, aber mehr Eigenarbeit fuer null Mehrwert.
- Pydantic-Schemas an FastAPI-Routern bleiben einzige Wahrheit — Frontend-Types sind generiert, nicht hand-gepflegt.

#### Tailwind-Pflicht
- Tailwind 3 (gleich wie Mockup) — bei der Frontend-Migration gleichzeitig auf Tailwind via Build-Step wechseln (CDN ist nur in HTMX-Prototypen-Phase OK). Build-Step ist sowieso da, also Vorteil mitnehmen (Purge, Variants, Custom-Theme).

---

## 3. Migrations-Pattern

### 3.1 Drei Optionen

| Pattern | Kernidee | Bewertung fuer dieses Projekt |
|---|---|---|
| **Big-Bang** | Frozen-Period: HTMX-Frontend abschalten, alles neu in SPA, dann Cut-Over. | ❌ |
| **Greenfield-Pilot** | Neue Module komplett im neuen Stack, alte unangetastet, kein Strangling. | 🟡 (Subset von Strangler) |
| **Strangler-Fig pro Modul** | SPA wird parallel hochgezogen, eine Modul-Migration nach der anderen, alte Module laufen weiter, bis sie ersetzt sind. | ✅ |

### 3.2 Bewertung Big-Bang — verworfen

- **Wertkurve katastrophal fuer Solo-Dev**: monatelange Phase, in der nichts ausgeliefert wird. Bestehende Bugs/Anpassungen in SEPA/Mietverwaltung muessten parallel gepflegt werden.
- "Fantastic Rewrites and How to Avoid Them" + branchen-Postmortems sind eindeutig: Big-Bang scheitert auch in groesseren Teams, fuer Solo-Devs ist es nahezu garantiert ([Quelle 1](https://frontendatscale.com/issues/19/), [Quelle 2](https://medium.com/@hashbyt/strangler-fig-vs-big-bang-migration-legacy-modernization-47d95ab9da60)).
- Bei laufender Produktion (`https://dashboard.dbshome.de` ist live, M5-Live-Tests stehen aus) ist Cut-Over-Risiko untragbar.

### 3.3 Bewertung Greenfield-Pilot

- Ein "echter" Greenfield-Pilot waere: neuer Repo, evtl. neues Backend, kein Bezug zum Bestand. **Hier nicht anwendbar** — Backend bleibt FastAPI, Daten bleiben in derselben Postgres.
- Die schwaechere Variante ("nur neue Module in der SPA, alte Module nie migrieren") ist ein **Subset von Strangler** — funktioniert ohne explizites Strangling, weil neue Module den alten Bestand nicht ersetzen, nur ergaenzen. Risiko: Inkonsistente UX zwischen `/cases/123` (HTMX) und `/objects/456` (SPA) auf Dauer. Akzeptabel als Anfangszustand, nicht als Endzustand.

### 3.4 Empfehlung: Strangler-Fig pro Modul

#### Phasenmodell

**Phase 0 — Plattform-Setup (5–8 PT)**
- Neuen `frontend/`-Ordner im Repo (Monorepo-Layout) mit Vite + React + TanStack Router + Query + Tailwind 3 + TS.
- Reverse-Proxy umkonfigurieren: `/app/*` → SPA-Static, alles andere → FastAPI (HTMX). Caddy-Config siehe Abschnitt 4.5.
- Auth-Bridge: Cookie-Session funktioniert auf beiden Seiten, weil Same-Origin. CSRF-Middleware (Double-Submit) eingehaengt fuer SPA-Mutationen.
- `@hey-api/openapi-ts`-Pipeline mit `npm run gen:api`.
- Dockerfile.frontend (Vite-Build → Caddy-Static-Layer); ggf. zweiter Container im Compose oder Static-Files in den FastAPI-Container kopiert (siehe 4.5 fuer Variante).
- CI erweitern: pnpm/npm install + tsc + vite build + Type-Diff vs. Backend.
- **Ergebnis**: leerer "Hello SPA"-Mount unter `/app`, der per Cookie authentifiziert ist und mit dem FastAPI-API redet. Beweispunkt fuer alles Folgende.

**Phase 1 — Erste neue Module direkt in SPA (Greenfield-im-Strangler)**
- Objektsteckbrief (M-naechste, neues Modul) wird **nicht mehr in HTMX gebaut**, sondern direkt in der SPA — Mockup ist da.
- Due-Radar als Kanban (Mockup ebenfalls vorhanden) ebenfalls direkt in SPA.
- Dashboard-Kacheln (Eintrittspunkte) bleiben zunaechst HTMX, aber Links springen ueber `/app/objects/...`.
- **Ergebnis**: Das Hauptproblem (HTMX skaliert nicht in komplexe UX) ist fuer alle *neuen* Module geloest, ohne dass alter Code angefasst wurde.
- **Effort pro Modul**: 8–15 PT bei kleiner UI, 20–35 PT bei komplexer Interaktion (Objektsteckbrief mit 8 Clustern, Review-Queue-Drawer, Provenance-Pills).

**Phase 2 — Bestand selektiv migrieren**
- Migrationsreihenfolge nach **Schmerz × Lerngewinn**:
  1. **Admin-Bereich** (Users, Roles, Audit-Log) — niedriger Schmerz, niedrige Komplexitaet, gutes SPA-Onboarding fuer Admin-Liste mit TanStack Table. **5–8 PT.**
  2. **Workflows-Edit** — Form mit Prompt + Modell + Lernnotizen. Bietet sich fuer SPA an (Markdown-Editor, Modell-Picker als Combobox, Live-Preview). **3–5 PT.**
  3. **Documents-Liste + Detail (SEPA)** — der HTMX-Polling-Mechanismus mappt 1:1 auf `useQuery({refetchInterval})`. Chat-Drawer wird zu globalem Drawer-Component. **15–25 PT** (PDF-iframe + Extraktions-Form + Chat).
  4. **Cases-Liste + Detail (Mietverwaltung)** — mit Abstand groesster Brocken (`case_detail.html` ~1019 Zeilen, 7 Sektionen, 13 Save-Routen, Status-Pills, Live-Refresh). **40–60 PT**, evtl. in Sub-Phasen (Liste + 1 Sektion zuerst).
- **Pro abgeschlossenem Modul**: HTMX-Template + Router-HTML-Response geloescht, Router liefert nur noch JSON. `/app/...`-Route uebernimmt.

**Phase 3 — Dashboard als SPA-Root + HTMX-Sunset**
- Wenn alle "regulaeren" User-Flows in der SPA sind, wird das Dashboard (`/`) auf SPA umgezogen. HTMX bleibt nur noch fuer `/auth/*` und ggf. `/health`.
- `Jinja2Templates`-Singleton kann reduziert werden auf reine OAuth-Callback-Pages und Error-Pages.

#### Personentage-Schaetzung total

| Phase | Effort |
|---|---|
| 0 — Plattform-Setup | 5–8 PT |
| 1 — Neue Module (Steckbrief + Due-Radar): | 30–50 PT |
| 2 — Bestand: Admin + Workflows | 8–13 PT |
| 2 — Bestand: SEPA-Modul | 15–25 PT |
| 2 — Bestand: Mietverwaltung | 40–60 PT |
| 3 — Dashboard + HTMX-Sunset | 5–10 PT |
| **Total** | **~100–170 PT** (Solo-Dev mit Claude Code) |

Wenn neue Module realistisch ~40 % der Gesamtarbeit sind (also sowieso anfallen), ist die "Migrations-Steuer" auf den Bestand ~70–100 PT. **Das ist die Zahl, die fuer Stakeholder-Diskussionen relevant ist.** Verteilbar ueber 6–9 Monate Kalenderzeit, nebenher zur Feature-Arbeit.

#### Erwartete Risiken
- **Auth-Bridge-Bugs in den ersten Wochen**: Cookie-Sharing zwischen HTMX und SPA hat Eckkasen (Refresh-Race, OAuth-Rueckkehr aus dem Subpath, CSRF-Token-Aktualitaet). Phase 0 muss hier gruendlich getestet werden.
- **State-Sync** zwischen HTMX-Pages und SPA-Pages, falls beide gleichzeitig offen sind in zwei Tabs (z. B. Mietverwaltung in HTMX-Tab editiert, Objektsteckbrief in SPA-Tab nutzt veraltete Daten). Loesbar via TanStack Query-Refetch-on-Focus.
- **Frontend-/Backend-Type-Drift** waehrend einer Migration: `npm run gen:api` muss reflexiv vor jedem Push laufen. Pre-Commit-Hook empfehlenswert.
- **Mockups sind nicht produktreif** — sie verwenden Mock-Daten in `src/data/mock.ts`. Beim Portieren sind die API-Schnittstellen erst noch zu definieren (Pydantic-Schemas + FastAPI-Routes). Faktor x1.5 auf die rohe Komponenten-Portierungs-Schaetzung einplanen.

---

## 4. Auth + Co-Existence

### 4.1 Empfehlung: Cookie-Session bleibt — kein JWT-Wechsel

**Begruendung**:
- Same-Origin-Setup. SPA-Static unter `dashboard.dbshome.de/app/`, API unter `dashboard.dbshome.de/api/`. **Kein CORS-Aufwand.** Cookie wird automatisch mitgesendet.
- HttpOnly-Cookie ist gegen XSS deutlich resilienter als ein JWT in `localStorage`. Die HTMX-Seite ist sowieso auf HttpOnly festgelegt; den gleichen Mechanismus fuer SPA zu nutzen ist die niedrigere Angriffsflaeche.
- Authlib + Starlette `SessionMiddleware` + `itsdangerous` funktionieren bereits — Logout ist ein Cookie-Clear, kein Token-Revocation noetig.
- JWT braeuchte: Refresh-Token-Logik, Storage-Strategie (im RAM? sessionStorage? HttpOnly-Cookie? — letzteres macht JWT zur Cookie-Session zurueck), Rotation, Server-side Revocation-List fuer Force-Logout. **Fuer Same-Origin-B2B-Tool: nicht gerechtfertigt.**

Quellen: [FastAPI-Security-Guide (2026)](https://blog.greeden.me/en/2025/10/14/a-beginners-guide-to-serious-security-design-with-fastapi-authentication-authorization-jwt-oauth2-cookie-sessions-rbac-scopes-csrf-protection-and-real-world-pitfalls/) — "Browser-zentriert: Cookie-Session ist die natuerliche Wahl." [StackHawk](https://www.stackhawk.com/blog/csrf-protection-in-fastapi/) — bestaetigt CSRF nur Pflicht, wenn Cookie-Auth genutzt wird.

### 4.2 CSRF-Strategie — Double-Submit-Cookie

Sobald die SPA Mutationen macht (POST/PUT/DELETE), brauchen wir CSRF-Schutz, denn Cookie-Auth ohne CSRF ist anfaellig.

**Setup**:
1. Bibliothek: `starlette-csrf` (Frankie567) oder `fastapi-csrf-protect` (aekasitt). Beide implementieren Double-Submit-Cookie. `starlette-csrf` ist kleiner, FastAPI-Idiomatik passt — bevorzugt.
2. Beim Login (oder beim ersten GET nach Login) setzt der Server zwei Cookies:
   - `session` (HttpOnly, Secure, SameSite=Lax) — bleibt unveraendert.
   - `csrftoken` (NICHT HttpOnly, Secure, SameSite=Lax) — fuer JS lesbar.
3. SPA liest `csrftoken` per `document.cookie` und sendet ihn als Header `X-CSRF-Token` bei jeder mutierenden Anfrage.
4. Server-Middleware vergleicht Cookie-Wert mit Header-Wert. Mismatch → 403.
5. **Fuer HTMX-Pages**: Token wird ins HTML als `<meta name="csrf-token" content="...">` gerendert; HTMX `htmx:configRequest`-Event-Listener haengt Header an. Existierender HTMX-Code wird also erweitert (kleiner Patch).

Quellen: [fastapi-csrf-protect](https://github.com/aekasitt/fastapi-csrf-protect), [starlette-csrf](https://github.com/frankie567/starlette-csrf), [stackhawk.com Erklaerung Double-Submit](https://www.stackhawk.com/blog/csrf-protection-in-fastapi/).

### 4.3 SameSite + Secure-Flags

| Cookie | HttpOnly | Secure | SameSite | Begruendung |
|---|---|---|---|---|
| `session` (Authlib) | ✅ | ✅ (Prod) | `Lax` | `Lax` reicht, weil OAuth-Redirect ein Top-Level-GET ist. `Strict` wuerde den OAuth-Callback brechen. |
| `csrftoken` | ❌ (JS muss lesen) | ✅ (Prod) | `Lax` | Wert ist alleine wertlos ohne gleichlaufendes Session-Cookie → kein Schutz-Verlust durch JS-Zugriff. |

In Dev (HTTP `localhost`): `Secure=False`. Existierender Code (`https_only=settings.app_env != "development"` aus `app/main.py`) bleibt das Muster.

### 4.4 OAuth-Callback funktioniert weiter

- Redirect-URI bleibt `https://dashboard.dbshome.de/auth/google/callback` — das ist eine FastAPI-Route, nicht in der SPA.
- Nach Callback setzt der Server das Session-Cookie + Redirect zu `/app/` (SPA-Root) statt `/` (Dashboard-HTMX). Konfigurierbar pro Phase der Migration.
- Wenn die SPA selbst feststellt, dass sie nicht eingeloggt ist (z. B. erste Antwort eines API-Calls ist 401): Redirect auf `/auth/google/login`. Standard-Pattern, in TanStack-Router via `beforeLoad` Guard auf der Root-Route.

### 4.5 Subpath-Mounting via Caddy

Elestio nutzt einen eigenen Reverse-Proxy auf der VM. Wir haben zwei Optionen:

**Option A — Static-Files vom FastAPI-Container ausliefern (einfach)**
- Vite-Build kopiert `dist/` in `app/static/spa/` waehrend des Docker-Builds (Multi-Stage).
- FastAPI mounted `/app` auf `app/static/spa` mit Fallback auf `index.html`.
- `app.mount("/app/assets", StaticFiles(directory="app/static/spa/assets"))` + Catch-All-Route die `index.html` zurueckgibt.
- **Vorteil**: ein Container, kein Compose-Aufwand. CSRF-Setup trivial, gleiche Domain.
- **Nachteil**: FastAPI serviert Static-Files (geht, aber Caddy/Nginx waeren effizienter; bei der erwarteten Last egal).

**Option B — Zweiter Container mit Caddy fuer Static-Files**
- Vite-Build → Caddy-Alpine-Image. Compose hat dann zwei Services + ein Caddyfile auf der Elestio-Proxy-Ebene oder ein internes Caddy.
- Caddyfile-Skizze:
  ```caddyfile
  dashboard.dbshome.de {
      handle /api/* { reverse_proxy app:8000 }
      handle /auth/* { reverse_proxy app:8000 }
      handle_path /app/* {
          root * /srv/spa
          try_files {path} /index.html
          file_server
      }
      handle { reverse_proxy app:8000 }
  }
  ```
- **Vorteil**: saubere Trennung, schnelles Static-File-Serving.
- **Nachteil**: Elestio-Reverse-Proxy ist bereits Caddy. Verhindern, dass wir einen "Caddy-im-Caddy" haben — entweder die Elestio-Proxy-Konfiguration direkt anpassen (Risiko: bei Elestio-Update wieder ueberschrieben) oder einen App-internen Caddy verwenden.

**Empfehlung**: **Option A** in Phase 0–1 (schnell, einfach, eine Deployment-Einheit). Bei Phase 3 (HTMX-Sunset) auf Option B oder zumindest expliziten Static-Server umsteigen, wenn Performance-Profile es rechtfertigt.

Quellen: [Caddy SPA-Pattern](https://haykot.dev/blog/serving-spas-and-api-with-caddy-v2/), [Caddyfile Common-Patterns](https://caddyserver.com/docs/caddyfile/patterns).

### 4.6 Co-Existence-Regeln

- **Pfad-Trennung**: HTMX bleibt unter `/`, SPA unter `/app/*`. Routing-Layer entscheidet.
- **Cookie-Domain**: identisch (`dashboard.dbshome.de`). Beide Welten teilen Session.
- **Logout**: ein Endpoint `/auth/logout` clearet Cookies + redirected. Egal welche Welt aufruft.
- **Permission-Checks**: API-Endpoints lesen `Depends(get_current_user)` weiterhin. Permissions identisch. SPA macht UI-Hide auf Basis eines `/api/me`-Calls (liefert Permissions), Server enforced trotzdem.
- **Audit-Log**: `audit()`-Helper kennt nur User + Action — egal ob Aufruf von HTMX oder SPA. Bleibt unveraendert.

---

## 5. Risiken + offene Punkte

### Stack
- **TanStack-Sustainability** ist gut, aber kein Microsoft-/Meta-Backing. Realistisches Risiko bleibt: 12-Monats-Horizont OK, 5-Jahres-Horizont nicht garantiert. Mitigation: Routing-Code ist nicht-trivial, aber portierbar zu React Router 7, sollte TanStack je in Funding-Krise geraten.
- **Vite-Major-Upgrades** (5 → 6 → 7 in den letzten 18 Monaten) bringen kleine Breaking-Changes. Nicht problematisch, aber jeder Upgrade braucht 1–2 PT.

### Migration
- **Mietverwaltung-Modul ist live noch nicht verifiziert** (M5 Live-Tests offen). Migration sollte nicht starten, bevor das aktuelle HTMX-UI live mindestens einen End-to-End-Fall erfolgreich gefahren hat — sonst verteilen wir das Reproduktions-Risiko zwischen Stack-Migration und Domain-Bug.
- **Story 1.4 Impower-Nightly-Mirror** und Steckbrief-Read-only-UI sind frisch. Wenn der Steckbrief in der SPA neu gebaut wird: aktuelle HTMX-Templates (`_obj_stammdaten.html`, `_obj_table_body.html`, `_obj_vorgaenge.html`) sind **Eingangsmaterial** fuer die SPA-Komponenten — nicht parallel doppelt pflegen.
- **Performance-Budget unter Doc-heavy Load**: Mietverwaltungs-Cases mit 20+ Mietvertraegen + Live-PDF-Vorschau im SPA-Detail koennten am 180-KB-Initial-Bundle kratzen, wenn PDF-Viewer gleich initial geladen wird. Mitigation: PDF-Viewer als separate Lazy-Chunk.

### Auth
- **Initial-Admin-Bootstrap**: aktuell `INITIAL_ADMIN_EMAILS` im OAuth-Callback. Bleibt unveraendert — die SPA macht keinen eigenen Bootstrap, der Server ist die Wahrheit.
- **CSRF-Token-Refresh**: Token muss bei Logout/Re-Login rotieren. `starlette-csrf` macht das nicht von alleine — hier reicht eine kleine Wrapper-Logik in der Login-Route.
- **OAuth-State-Cookie + CSRF-Cookie + Session-Cookie = drei Cookies.** Cookie-Header-Limit (4 KB) ist relevant, sollte aber locker reichen. Im Auge behalten beim Debuggen ungeklaerter 401/403.

### Operational
- **CI-Build-Zeit** waechst durch Frontend-Build um 1–3 min. GitHub-Actions auf der `docker-build.yml` muss ggf. `actions/cache` fuer `node_modules` einsetzen.
- **Image-Groesse**: Multi-Stage-Build (Node-Base fuer Build, Python-Base fuer Runtime) verhindert Bloat. Erwartung: Final-Image bleibt unter 400 MB (aktuell ~250 MB).

---

## 6. Anhang — Hauptquellen

### Stack-Vergleich
- [TanStack Start vs Next.js — offizielle Vergleichs-Doku](https://tanstack.com/start/latest/docs/framework/react/start-vs-nextjs)
- [TanStack Start v1.0 Release-Notes / RC-Status](https://byteiota.com/tanstack-start-v1-0-type-safe-react-framework-2026/)
- [TanStack 2-Years State + Funding-Modell](https://tanstack.com/blog/tanstack-2-years)
- [TanStack Router Code-Splitting-Doku](https://tanstack.com/router/latest/docs/guide/automatic-code-splitting)
- [React SSR Benchmark TanStack vs Next.js vs RR](https://blog.platformatic.dev/react-ssr-framework-benchmark-tanstack-start-react-router-nextjs)
- [Why developers leave Next.js for TanStack Start (Appwrite)](https://appwrite.io/blog/post/why-developers-leaving-nextjs-tanstack-start)
- [Next.js Vendor-Lock-In Architektur (Medium)](https://medium.com/@ss-tech/the-next-js-vendor-lock-in-architecture-a0035e66dc18)
- [Next.js Self-Hosting Guide 2025/2026](https://nextjs.org/docs/app/guides/self-hosting)
- [Vercel: anti-vendor-lock-in cloud (Gegenposition)](https://vercel.com/blog/vercel-the-anti-vendor-lock-in-cloud)
- [React Router 7 + Remix Merge — Offiziell](https://remix.run/blog/merging-remix-and-react-router)
- [LogRocket: Choosing the right RR7 mode](https://blog.logrocket.com/react-router-v7-modes/)
- [Svelte vs React 2025 — Brutally Honest (Medium)](https://medium.com/@techsam19/react-vs-sveltekit-in-2025-the-brutally-honest-comparison-3e4dc466e96a)
- [SPA vs SSR fuer Authenticated Dashboards](https://appmaster.io/blog/ssr-vs-spa-authenticated-dashboards)

### Migration
- [Strangler-Fig Pattern — Frontend-Anwendung (Medium)](https://medium.com/@felipegaiacharly/strangler-pattern-for-frontend-865e9a5f700f)
- [Strangler Fig vs Big Bang Migration (Medium)](https://medium.com/@hashbyt/strangler-fig-vs-big-bang-migration-legacy-modernization-47d95ab9da60)
- [Fantastic Rewrites and How to Avoid Them (Frontend at Scale)](https://frontendatscale.com/issues/19/)
- [Why all application migrations should be incremental (Vercel)](https://vercel.com/blog/incremental-migrations)
- [Frontend Migration Strategien (Medium)](https://medium.com/syngenta-digitalblog/navigating-frontend-migration-strategies-for-refactoring-rewriting-and-embracing-microfrontends-331520cde2bb)
- [HTMX als SPA-Alternative + Migration-Sweetspots](https://htmx.org/essays/spa-alternative/)

### Auth
- [Authlib + FastAPI Doku](https://docs.authlib.org/en/latest/client/fastapi.html)
- [FastAPI Security Comprehensive Guide 2026](https://blog.greeden.me/en/2025/10/14/a-beginners-guide-to-serious-security-design-with-fastapi-authentication-authorization-jwt-oauth2-cookie-sessions-rbac-scopes-csrf-protection-and-real-world-pitfalls/)
- [StackHawk CSRF Protection FastAPI](https://www.stackhawk.com/blog/csrf-protection-in-fastapi/)
- [starlette-csrf (Frankie567) GitHub](https://github.com/frankie567/starlette-csrf)
- [fastapi-csrf-protect (aekasitt) GitHub](https://github.com/aekasitt/fastapi-csrf-protect)

### Type-Generation
- [Hey API openapi-ts (TanStack Query Plugin)](https://heyapi.dev/openapi-ts/plugins/tanstack-query)
- [openapi-typescript + openapi-fetch + openapi-react-query](https://openapi-ts.dev/openapi-react-query/)
- [FastAPI Generating SDKs](https://fastapi.tiangolo.com/advanced/generate-clients/)
- [Vinta: FastAPI + Next.js Monorepo SDK-Pipeline](https://www.vintasoftware.com/blog/nextjs-fastapi-monorepo)

### Static-Hosting + Caddy
- [Caddy: Serving SPAs with API](https://haykot.dev/blog/serving-spas-and-api-with-caddy-v2/)
- [Caddyfile Common Patterns](https://caddyserver.com/docs/caddyfile/patterns)

### Bundle-Budgets
- [Performance Budgets for React Applications](https://medium.com/@vasanthancomrads/performance-budgets-for-react-applications-7e796da09ef8)
- [Reducing JS Bundle Size 2025 (Frontend-Tools)](https://www.frontendtools.tech/blog/reduce-javascript-bundle-size-2025)

---

**Naechster Schritt**: Dieses Dokument ist Foundation fuer
- `bmad-create-ux-design` (UX-Spec mit konkreten Komponenten + Hanseatic-Design-System) — kann parallel laufen,
- `bmad-create-architecture` (Architektur-Doc, das Stack-Wahl + Migrations-Phasenmodell + Auth-Setup in konkrete Datei-Strukturen, Repo-Layout, CI-Pipelines uebersetzt).
