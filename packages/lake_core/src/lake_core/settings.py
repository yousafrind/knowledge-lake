"""Typed settings. The only module in the repo that reads the environment."""

from pathlib import Path

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)


class Settings(BaseSettings):
    """Required values have no default, so a missing one fails at startup."""

    model_config = SettingsConfigDict(
        env_prefix="LAKE_", toml_file="config/lake.toml", extra="ignore"
    )

    database_url: str
    s3_endpoint: str
    s3_key: str
    s3_secret: str
    s3_bucket: str = "lake"
    embedder: str = "bge-small"  # or "hash" (offline, lexical only)
    config_dir: Path = Path("config")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Priority: explicit args, then environment, then config/lake.toml.
        return (init_settings, env_settings, TomlConfigSettingsSource(settings_cls))


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from env / toml
