from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    secret_key: str = "dev-secret-change-me"
    base_url: str = "http://localhost:8000"

    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_user: str = "dashboard"
    postgres_password: str = ""
    postgres_db: str = "dashboard"

    google_client_id: str = ""
    google_client_secret: str = ""
    google_hosted_domain: str = "dbshome.de"

    anthropic_api_key: str = ""

    impower_base_url: str = "https://api.app.impower.de"
    impower_bearer_token: str = ""

    # Facilioo-API (Workflow: ETV-Unterschriftenliste).
    # Token ist ein langlebiges JWT ("platform api_token", manuell rotieren).
    facilioo_base_url: str = "https://api.facilioo.de"
    facilioo_bearer_token: str = ""
    facilioo_rate_interval_seconds: float = 1.0
    """Mindest-Abstand zwischen Facilioo-Requests (Sekunden), gilt im
    Mirror-Pfad (Story 4.3). ETV-Pfad ueberspringt den Gate via
    rate_gate=False, weil Aggregator 60+ parallele Calls benoetigt."""

    uploads_dir: str = "uploads"
    max_upload_mb: int = 20

    # Komma-separierte Liste von E-Mails, die beim ersten Login automatisch
    # die admin-Rolle erhalten. Existierende Admin-Zuweisungen bleiben
    # unberuehrt — der Bootstrap-Hook promotet nur neue User bzw. User
    # ohne Rolle.
    initial_admin_emails: str = ""

    # Nightly-Mirror-Schalter: in Tests + Dev auf False setzen, damit der
    # Scheduler keinen echten Impower-Call ausloest. Prod default True.
    impower_mirror_enabled: bool = True

    # Facilioo-Ticket-Mirror (Story 4.3) — 1-Min-Poll-Job.
    # Default False: lokal `python -m app.main` pollt nicht, Tests/Dev sind
    # safe by default. Prod setzt FACILIOO_MIRROR_ENABLED=true via Env.
    facilioo_mirror_enabled: bool = False
    facilioo_poll_interval_seconds: float = 60.0
    # Error-Budget: > 10 % fehlgeschlagene Polls in 24 h → Alert-Audit.
    facilioo_error_budget_threshold: float = 0.10
    facilioo_error_budget_window_hours: int = 24
    facilioo_error_budget_min_sample: int = 10

    # Optional: separater Encryption-Key fuer Steckbrief-Felder (entry_code_*).
    # Leer = Fallback auf secret_key. Prod: eigenen Zufallsschluessel setzen.
    steckbrief_field_key: str = ""

    # Foto-Backend (ID1 — Photo-Pipeline)
    # Bewusste Abweichung von architecture.md §ID1 (Default "sharepoint"):
    # Default "local" vermeidet M365-Admin-Ticket fuer lokale Entwicklung.
    # Prod setzt PHOTO_BACKEND=sharepoint via Env-Override (Elestio).
    photo_backend: str = "local"  # "sharepoint" | "local"
    sharepoint_tenant_id: str = ""
    sharepoint_client_id: str = ""
    sharepoint_client_secret: str = ""
    sharepoint_site_id: str = ""
    sharepoint_drive_id: str = ""

    @property
    def initial_admin_email_set(self) -> set[str]:
        return {
            e.strip().lower()
            for e in self.initial_admin_emails.split(",")
            if e.strip()
        }

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
