"""Configuración del servicio (variables de entorno / archivo .env)."""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Base de datos
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/spp_evaluacion"
    auto_create_tables: bool = False

    # CORS
    cors_origins: str = "*"

    # Autenticación
    auth_mode: Literal["dev", "jwt"] = "jwt"
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"

    # IA
    llm_provider: Literal["auto", "anthropic", "openai_compat", "mock"] = "openai_compat"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_api_key: str = ""
    llm_model: str = "gemini-3.8-flash"
    llm_max_tokens: int = 8000
    max_context_chars: int = 60000
    max_file_mb: int = 15

    # Servicio de evidencias
    evidencias_mode: Literal["stub", "practice_db", "http"] = "practice_db"
    evidencias_api_url: str = ""
    evidencias_api_token: str = ""
    practice_database_url: str = ""
    allowed_file_hosts: str = "res.cloudinary.com"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_effective(self) -> str:
        """Proveedor que realmente se usará."""
        if self.llm_provider == "auto":
            if self.anthropic_api_key:
                return "anthropic"
            return "openai_compat" if (self.llm_base_url and self.llm_model) else "mock"
        return self.llm_provider

    @property
    def llm_model_name(self) -> str:
        """Nombre del modelo que se usará (para mostrar y registrar)."""
        return {"anthropic": self.anthropic_model, "openai_compat": self.llm_model}.get(self.llm_effective, "simulado")


@lru_cache
def get_settings() -> Settings:
    return Settings()
