import json
from contextlib import suppress
from threading import Lock
from time import monotonic
from uuid import uuid4

import pycountry
from pydantic import BaseModel, ConfigDict, Field, field_validator

from keitaro_wrapper.errors import AppError, KeitaroError
from keitaro_wrapper.keitaro import Campaign, Keitaro, PositiveId, Reference, Stream

GOOGLE_URL = "https://www.google.com/"
OFFER_CATALOG_TTL = 15
OFFER_SEARCH_LIMIT = 20


class CreateCampaign(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    country: str = Field(min_length=2, max_length=2)
    offer_id: PositiveId
    domain_id: PositiveId
    group_id: PositiveId
    traffic_source_id: PositiveId

    @field_validator("country")
    @classmethod
    def iso_country(cls, value: str) -> str:
        value = value.upper()
        if pycountry.countries.get(alpha_2=value) is None:
            raise ValueError("Введите двухбуквенный код страны, например AU.")
        return value


class Campaigns:
    def __init__(self, tracker: Keitaro, prefix: str):
        self.tracker = tracker
        self.prefix = prefix
        self._offer_catalog: list[Reference] = []
        self._offer_catalog_expires = 0.0
        self._offer_catalog_lock = Lock()

    def owned(self, campaign_id: int) -> Campaign:
        campaign = self.tracker.get(f"/campaigns/{campaign_id}", Campaign)
        if campaign.id != campaign_id or not campaign.name.startswith(self.prefix):
            raise AppError(403, "Открыть можно только кампанию с настроенным тестовым префиксом.")
        if campaign.state == "deleted":
            raise AppError(404, "Кампания находится в архиве Keitaro.")
        return campaign

    def lookups(self) -> dict[str, list[Reference]]:
        lookups = {
            "domains": self.tracker.list("/domains", Reference),
            "groups": self.tracker.list("/groups", Reference, type="campaigns"),
            "sources": self.tracker.list("/traffic_sources", Reference),
        }
        return {
            name: [item for item in items if item.state != "deleted"]
            for name, items in lookups.items()
        }

    def offer(self, offer_id: int) -> Reference:
        offer = self.tracker.get(f"/offers/{offer_id}", Reference)
        if offer.id != offer_id or offer.state == "deleted":
            raise AppError(404, "Оффер недоступен в Keitaro. Выберите другой оффер.")
        return offer

    def offer_catalog(self) -> list[Reference]:
        with self._offer_catalog_lock:
            if monotonic() >= self._offer_catalog_expires:
                self._offer_catalog = self.tracker.list("/offers", Reference)
                self._offer_catalog_expires = monotonic() + OFFER_CATALOG_TTL
            return self._offer_catalog

    def inline_offer_choices(self) -> list[Reference] | None:
        with self._offer_catalog_lock:
            if (
                monotonic() >= self._offer_catalog_expires
                or len(self._offer_catalog) > OFFER_SEARCH_LIMIT
            ):
                return None
            return [offer for offer in self._offer_catalog if offer.state != "deleted"]

    def search_offers(self, query: str) -> list[Reference]:
        if not query:
            return []
        if query.isascii() and query.isdecimal() and 0 < int(query) <= 2**31 - 1:
            try:
                return [self.offer(int(query))]
            except AppError as error:
                if error.status == 404:
                    return []
                raise
        return [
            offer
            for offer in self.offer_catalog()
            if offer.state != "deleted" and query.casefold() in offer.name.casefold()
        ][:OFFER_SEARCH_LIMIT]

    def create(self, data: CreateCampaign) -> Campaign:
        self.offer(data.offer_id)
        name = data.name if data.name.startswith(self.prefix) else self.prefix + data.name
        alias = self.prefix.replace("_", "-") + uuid4().hex[:12]
        campaign = self.tracker.write(
            "POST",
            "/campaigns",
            {
                "name": name,
                "alias": alias,
                "type": "position",
                "state": "disabled",
                "domain_id": data.domain_id,
                "group_id": str(data.group_id),
                "traffic_source_id": data.traffic_source_id,
            },
            Campaign,
        )
        try:
            if campaign.name != name or campaign.state != "disabled":
                raise KeitaroError("Keitaro не подтвердил создание выключенной кампании.")
            self._create_streams(campaign.id, data)
            active = self.tracker.write(
                "PUT", f"/campaigns/{campaign.id}", {"state": "active"}, Campaign
            )
            if active.id != campaign.id or active.state != "active":
                raise KeitaroError("Keitaro не подтвердил включение кампании.")
        except AppError as error:
            raise KeitaroError(
                f"Результат создания кампании №{campaign.id} не подтверждён. "
                f"Проверьте её в Keitaro перед повторной попыткой. {error}",
                error.status if error.status >= 500 else 502,
            ) from None
        return active

    def _create_streams(self, campaign_id: int, data: CreateCampaign) -> None:
        redirect = self.tracker.write(
            "POST",
            "/streams",
            {
                "campaign_id": campaign_id,
                "type": "regular",
                "position": 1,
                "name": f"{data.country} to Google",
                "schema": "redirect",
                "action_type": "http",
                "action_payload": GOOGLE_URL,
                "collect_clicks": True,
                "filters": [{"name": "country", "mode": "accept", "payload": [data.country]}],
            },
            Stream,
        )
        offers = self.tracker.write(
            "POST",
            "/streams",
            {
                "campaign_id": campaign_id,
                "type": "default",
                "position": 2,
                "name": "Offers",
                "schema": "landings",
                "action_type": "do_nothing",
                "collect_clicks": True,
                "offers": [{"offer_id": data.offer_id, "share": 100, "state": "active"}],
            },
            Stream,
        )
        streams = self.tracker.list(f"/campaigns/{campaign_id}/streams", Stream)
        by_id = {stream.id: stream for stream in streams}
        first = by_id.get(redirect.id)
        second = by_id.get(offers.id)
        if (
            len(streams) != 2
            or first is None
            or first.campaign_id != campaign_id
            or first.type != "regular"
            or first.schema_ != "redirect"
            or first.state != "active"
            or first.action_payload != GOOGLE_URL
            or not matches_country(first.filters, data.country)
            or second is None
            or second.campaign_id != campaign_id
            or second.type != "default"
            or second.schema_ != "landings"
            or second.state != "active"
            or len(second.offers) != 1
            or second.offers[0].offer_id != data.offer_id
            or second.offers[0].share != 100
            or second.offers[0].state != "active"
        ):
            raise KeitaroError("Keitaro не подтвердил настройки двух потоков.")


def matches_country(filters: list[dict[str, object]], country: str) -> bool:
    if len(filters) != 1:
        return False
    rule = filters[0]
    payload = rule.get("payload")
    if isinstance(payload, str):
        with suppress(ValueError):
            payload = json.loads(payload)
    return (
        rule.get("name") == "country"
        and rule.get("mode") == "accept"
        and payload in ([country], country)
    )
