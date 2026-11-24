from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import firmware as fw


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://luz:luz@localhost:5432/luz"

    # --- MQTT (mesmos valores do firmware por padrão) ---
    mqtt_enabled: bool = True
    mqtt_host: str = "broker.hivemq.com"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_tls: bool = False
    # Prefixo do client ID do backend. Um sufixo aleatório é sempre adicionado
    # para não colidir com SensorNode01 / atuador01.
    mqtt_client_id_prefix: str = "luz-dashboard"
    # Assina tudo sob a base: tópicos conhecidos são interpretados e os demais
    # (ex.: futuro servo) ficam guardados em mqtt_messages como "nao_tratado".
    mqtt_subscribe: str = f"{fw.TOPIC_BASE}/#"
    # Contrato v1.1: o backend assina tudo e é o único que publica comandos
    mqtt_subscribe_v1: str = "luzambiente/v1/#"
    mqtt_keepalive: int = 30
    mqtt_reconnect_min_s: float = 1.0
    mqtt_reconnect_max_s: float = 30.0

    # --- Modo demonstração (dados sintéticos, isolados por is_demo=true) ---
    demo_mode: bool = False
    demo_interval_s: float = 1.0

    # --- API ---
    cors_origins: str = "http://localhost:5173,http://localhost:8080"
    max_page_size: int = 1000
    store_raw_payloads: bool = True

    watchdog_interval_s: float = Field(default=1.0, gt=0)

    # --- Autenticação (R9) e perfis (R16): "nome:senha:perfil,..." no .env ---
    auth_users: str = ""
    auth_secret: str | None = None
    auth_ttl_h: float = 12

    # --- Notificação externa (R15) ---
    ntfy_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    notify_min_severity: str = "critico"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
