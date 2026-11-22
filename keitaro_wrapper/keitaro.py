from types import GenericAlias
from typing import TYPE_CHECKING, Annotated, Literal, TypeVar, cast

import httpx
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from keitaro_wrapper.domain import OfferRow, Percent
from keitaro_wrapper.errors import AppError, KeitaroError

if TYPE_CHECKING:
    from typing_extensions import TypeForm

Entity = TypeVar("Entity", bound=BaseModel)
Payload = TypeVar("Payload")
PositiveId = Annotated[int, Field(gt=0, le=2**31 - 1)]

UPSTREAM_ERRORS = {
    400: "Keitaro отклонил параметры запроса. Проверьте введённые данные.",
    401: "Keitaro не принял ключ Admin API. Проверьте ключ в настройках приложения.",
    403: "Keitaro отказал в доступе. Проверьте доступ к трекеру и права ключа Admin API.",
    409: "Данные в Keitaro изменились. Откройте кампанию заново и проверьте изменения.",
    422: "Keitaro отклонил данные. Проверьте выбранные значения.",
    429: "Keitaro ограничил частоту запросов. Повторите попытку позже.",
}


class Reference(BaseModel):
    id: PositiveId
    name: str
    state: str | None = None


class Campaign(Reference):
    alias: str


class RemoteOffer(BaseModel):
    offer_id: PositiveId
    share: Percent
    state: Literal["active", "disabled"] = "active"


class Stream(Reference):
    campaign_id: PositiveId
    schema_: str = Field(alias="schema")
    position: int = 0
    offers: list[RemoteOffer] = Field(default_factory=list)
    action_payload: str | dict[str, object] | None = None
    filters: list[dict[str, object]] = Field(default_factory=list)
    type: str

    def offer_rows(self) -> list[OfferRow]:
        return [OfferRow.model_validate(offer.model_dump()) for offer in self.offers]


class Keitaro:
    def __init__(self, client: httpx.Client):
        self.client = client

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
    ) -> object:
        try:
            response = self.client.request(method, path, params=params, json=json)
            response.raise_for_status()
        except httpx.TimeoutException:
            raise KeitaroError("Время ожидания ответа Keitaro истекло.", 504) from None
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status == 404:
                raise AppError(404, "Запись не найдена в Keitaro. Проверьте ID.") from None
            message = UPSTREAM_ERRORS.get(status, "Не удалось выполнить запрос к Keitaro.")
            if status >= 500:
                message = "Ошибка сервера Keitaro. Проверьте доступность трекера."
            raise KeitaroError(f"{message} (HTTP {status})") from None
        except httpx.RequestError:
            raise KeitaroError(
                "Не удалось подключиться к Keitaro. Проверьте адрес и соединение."
            ) from None
        try:
            return response.json()
        except ValueError:
            raise KeitaroError("Keitaro вернул ответ в неверном формате.") from None

    def get(self, path: str, model: type[Entity]) -> Entity:
        return self._parse(TypeAdapter[Entity](model), self._request("GET", path))

    def list(self, path: str, model: type[Entity], **params: str) -> list[Entity]:
        items = cast("TypeForm[list[Entity]]", GenericAlias(list, model))
        adapter = TypeAdapter(items)
        return self._parse(adapter, self._request("GET", path, params=params))

    def write(
        self,
        method: Literal["POST", "PUT"],
        path: str,
        data: dict[str, object],
        model: type[Entity],
    ) -> Entity:
        try:
            return self._parse(TypeAdapter[Entity](model), self._request(method, path, json=data))
        except KeitaroError as error:
            if method == "POST" and path == "/campaigns":
                raise KeitaroError(
                    f"{error} Перед повтором проверьте список кампаний в Keitaro.", error.status
                ) from None
            raise

    @staticmethod
    def _parse(adapter: TypeAdapter[Payload], data: object) -> Payload:
        try:
            return adapter.validate_python(data)
        except ValidationError:
            raise KeitaroError("Структура данных в ответе Keitaro не соответствует API.") from None
