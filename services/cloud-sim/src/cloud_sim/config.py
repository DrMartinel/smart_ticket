"""cloud-sim settings, read from the repo root's `.env` or the environment, with no defaults."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# The repo root's .env, from services/cloud-sim/src/cloud_sim/config.py.
ENV_FILE = Path(__file__).resolve().parents[4] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_ignore_empty=True, extra="ignore")

    # The service account core-api signs in with (F17 §h.3).
    service_user: str = Field(validation_alias="OPENSTACK_SERVICE_USER")
    service_password: SecretStr = Field(validation_alias="OPENSTACK_SERVICE_PASSWORD")
    # Where logs and traces go: the APM Server's OTLP/HTTP endpoint.
    otlp_endpoint: str = Field(validation_alias="CLOUD_SIM_OTLP_ENDPOINT")
    # Seconds between telemetry ticks.
    tick_sec: float = Field(validation_alias="CLOUD_SIM_TICK_SEC", gt=0)
    # Seconds a reboot, start, stop or detach takes to finish.
    transition_sec: float = Field(validation_alias="CLOUD_SIM_TRANSITION_SEC", ge=0)
    # Seconds a Keystone token lives.
    token_ttl_sec: int = Field(validation_alias="CLOUD_SIM_TOKEN_TTL_SEC", gt=0)
