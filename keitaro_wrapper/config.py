from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    keitaro_url: HttpUrl
    keitaro_api_key: SecretStr
    campaign_prefix: str = Field(pattern=r"^test_[a-z0-9]{2,30}_$")
    database_url: str = "sqlite:///keitaro.db"

    @field_validator("keitaro_url")
    @classmethod
    def tracker_origin(cls, value: HttpUrl) -> HttpUrl:
        if (
            value.scheme != "https"
            or value.path not in ("/", "", None)
            or value.username
            or value.password
            or value.query
            or value.fragment
        ):
            raise ValueError("Укажите HTTPS-адрес трекера без пути, логина и пароля.")
        return value

    @field_validator("keitaro_api_key")
    @classmethod
    def nonempty_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value()
        if not key or any(not 33 <= ord(char) <= 126 for char in key):
            raise ValueError("Укажите корректный ключ Admin API Keitaro.")
        return value
