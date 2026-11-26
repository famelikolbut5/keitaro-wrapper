from contextlib import suppress
from threading import Lock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from keitaro_wrapper.campaigns import Campaigns
from keitaro_wrapper.database import StreamState
from keitaro_wrapper.domain import OfferRow, matches_offers, merge_remote, normalize, outbound
from keitaro_wrapper.errors import AppError, KeitaroError
from keitaro_wrapper.keitaro import Campaign, PositiveId, Stream


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)


class Edit(Revision):
    action: Literal["add", "remove", "restore", "pin", "unpin"]
    offer_id: PositiveId


class StreamView(BaseModel):
    id: int
    name: str
    schema_: str = Field(serialization_alias="schema")
    revision: int
    published: list[OfferRow]
    draft: list[OfferRow] | None
    conflict: bool

    @classmethod
    def from_row(cls, row: StreamState) -> "StreamView":
        return cls(
            id=row.id,
            name=row.name,
            schema_=row.schema,
            revision=row.revision,
            published=read_rows(row.published),
            draft=read_rows(row.draft) if row.draft is not None else None,
            conflict=row.conflict,
        )


class CampaignView(BaseModel):
    campaign: Campaign
    streams: list[StreamView]


def read_rows(data: list[dict[str, object]]) -> list[OfferRow]:
    return [OfferRow.model_validate(item) for item in data]


def dump_rows(rows: list[OfferRow]) -> list[dict[str, object]]:
    return [row.model_dump() for row in rows]


def rebalance_draft(rows: list[OfferRow]) -> list[dict[str, object]] | None:
    active = [row for row in rows if row.state == "active"]
    if active and sum(row.share for row in active) != 100:
        with suppress(AppError):
            return dump_rows(normalize(rows))
    return None


def changed_rows(rows: list[OfferRow], edit: Edit) -> list[OfferRow]:
    index = next((i for i, row in enumerate(rows) if row.offer_id == edit.offer_id), None)
    if index is None:
        if edit.action != "add":
            raise AppError(404, "Оффер не найден в этом потоке.")
        return normalize([*rows, OfferRow(offer_id=edit.offer_id, share=0)])

    row = rows[index]
    if edit.action == "add" and row.state != "removed":
        raise AppError(409, "Оффер уже в потоке.")
    if edit.action in ("add", "restore") and row.state == "removed":
        new = row.model_copy(update={"state": "active"})
    elif edit.action == "remove" and row.state in ("active", "disabled"):
        new = row.model_copy(update={"state": "removed", "share": 0, "pinned": False})
    elif edit.action in ("pin", "unpin") and row.state == "active":
        if edit.action == "pin" and row.share == 0:
            raise AppError(422, "Закрепить можно только положительную долю.")
        new = row.model_copy(update={"pinned": edit.action == "pin"})
        if edit.action == "pin":
            return [*rows[:index], new, *rows[index + 1 :]]
    else:
        raise AppError(409, "Действие недоступно для оффера в текущем состоянии.")

    return normalize([*rows[:index], new, *rows[index + 1 :]])


class Editor:
    def __init__(self, campaigns: Campaigns, sessions: sessionmaker[Session]):
        self.campaigns = campaigns
        self.tracker = campaigns.tracker
        self.sessions = sessions
        self.lock = Lock()

    def occupied_offers(self, stream_id: int) -> frozenset[int]:
        with self.sessions() as db:
            row = db.get(StreamState, stream_id)
            if row is None:
                raise AppError(404, "Сначала откройте кампанию по ID.")
            current = row.draft if row.draft is not None else row.published
            return frozenset(
                offer.offer_id for offer in read_rows(current) if offer.state != "removed"
            )

    def sync(self, campaign_id: int) -> CampaignView:
        with self.lock:
            campaign = self.campaigns.owned(campaign_id)
            streams = self.tracker.list(f"/campaigns/{campaign_id}/streams", Stream)
            if any(stream.campaign_id != campaign_id for stream in streams):
                raise KeitaroError("Keitaro вернул поток другой кампании.")
            ordered = sorted(
                (stream for stream in streams if stream.state != "deleted"),
                key=lambda stream: (stream.position, stream.id),
            )
            with self.sessions.begin() as db:
                return CampaignView(
                    campaign=campaign,
                    streams=[StreamView.from_row(self._sync(db, stream)) for stream in ordered],
                )

    def edit(self, stream_id: int, data: Edit) -> StreamView:
        with self.lock:
            row = self._read(stream_id, data.revision)
            self._check_editable(row)
            rows = read_rows(row.draft if row.draft is not None else row.published)
            if data.action in ("add", "restore"):
                self.campaigns.offer(data.offer_id)
            draft = dump_rows(changed_rows(rows, data))
            with self.sessions.begin() as db:
                current = self._get(db, stream_id, data.revision)
                current.draft = None if draft == current.published else draft
                current.revision += 1
                return StreamView.from_row(current)

    def cancel(self, stream_id: int, data: Revision) -> StreamView:
        with self.lock, self.sessions.begin() as db:
            row = self._get(db, stream_id, data.revision)
            row.draft = None
            row.conflict = False
            row.revision += 1
            return StreamView.from_row(row)

    def publish(self, stream_id: int, data: Revision) -> StreamView:
        with self.lock:
            row = self._read(stream_id, data.revision)
            self._check_editable(row)
            if row.draft is None:
                raise AppError(409, "В потоке нет черновика для публикации.")
            self.campaigns.owned(row.campaign_id)
            path = f"/streams/{stream_id}"
            remote = self.tracker.get(path, Stream)
            self._check_remote(row, remote)
            candidate = normalize(read_rows(row.draft))
            baseline = read_rows(row.published)
            actual = remote.offer_rows()
            if not matches_offers(candidate, actual):
                if not matches_offers(baseline, actual):
                    with self.sessions.begin() as db:
                        self._sync(db, remote)
                    raise AppError(
                        409, "Офферы изменились в Keitaro. Обновите страницу и проверьте черновик."
                    )
                failure = ""
                try:
                    self.tracker.write("PUT", path, {"offers": outbound(candidate)}, Stream)
                except KeitaroError as error:
                    failure = f"{error} "
                confirmed = self.tracker.get(path, Stream)
                self._check_remote(row, confirmed)
                if not matches_offers(candidate, confirmed.offer_rows()):
                    raise KeitaroError(
                        f"{failure}Keitaro не подтвердил публикацию долей. Черновик сохранён."
                    )

            with self.sessions.begin() as db:
                current = self._get(db, stream_id, data.revision)
                current.published = dump_rows(candidate)
                current.draft = None
                current.revision += 1
                return StreamView.from_row(current)

    def _read(self, stream_id: int, revision: int) -> StreamState:
        with self.sessions() as db:
            return self._get(db, stream_id, revision)

    @staticmethod
    def _get(db: Session, stream_id: int, revision: int) -> StreamState:
        row = db.get(StreamState, stream_id)
        if row is None:
            raise AppError(404, "Сначала откройте кампанию по ID.")
        if row.revision != revision:
            raise AppError(409, "Поток изменился. Обновите страницу перед редактированием.")
        return row

    @staticmethod
    def _check_editable(row: StreamState) -> None:
        if row.schema != "landings":
            raise AppError(422, "В этом типе потока нельзя редактировать офферы.")
        if row.conflict:
            raise AppError(409, "Поток изменился в Keitaro. Проверьте черновик и актуальные доли.")

    @staticmethod
    def _check_remote(row: StreamState, remote: Stream) -> None:
        if remote.id != row.id or remote.campaign_id != row.campaign_id:
            raise AppError(409, "Поток больше не принадлежит этой кампании.")
        if remote.schema_ != row.schema or remote.state == "deleted":
            raise AppError(409, "Состояние потока изменилось в Keitaro. Обновите страницу.")

    @staticmethod
    def _sync(db: Session, stream: Stream) -> StreamState:
        row = db.get(StreamState, stream.id)
        actual = stream.offer_rows()
        if row is None:
            row = StreamState(
                id=stream.id,
                campaign_id=stream.campaign_id,
                name=stream.name,
                schema=stream.schema_,
                published=dump_rows(actual),
                draft=rebalance_draft(actual) if stream.schema_ == "landings" else None,
                conflict=False,
                revision=1,
            )
            db.add(row)
            return row

        if row.campaign_id != stream.campaign_id:
            raise AppError(409, "Поток принадлежит другой кампании.")
        previous = read_rows(row.published)
        schema_changed = row.schema != stream.schema_
        offers_changed = not matches_offers(previous, actual)
        if not (schema_changed or offers_changed or row.name != stream.name):
            return row

        merged = merge_remote(previous, actual)
        row.published = dump_rows(merged)
        row.schema = stream.schema_
        row.name = stream.name
        row.revision += 1
        if row.draft is not None and (schema_changed or offers_changed):
            row.conflict = True
        elif stream.schema_ == "landings" and (schema_changed or offers_changed):
            row.draft = rebalance_draft(merged)
        return row
