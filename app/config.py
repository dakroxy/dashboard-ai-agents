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

    uploads_dir: str = "uploads"
    max_upload_mb: int = 20

    # Komma-separierte Liste von E-Mails, die beim ersten Login automatisch
    # die admin-Rolle erhalten. Existierende Admin-Zuweisungen bleiben
    # unberuehrt — der Bootstrap-Hook promotet nur neue User bzw. User
    # ohne Rolle.
    initial_admin_emails: str = ""

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
