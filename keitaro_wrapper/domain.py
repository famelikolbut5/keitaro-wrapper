from typing import Annotated, Literal

from pydantic import BaseModel, Field

from keitaro_wrapper.errors import AppError

Percent = Annotated[int, Field(ge=0, le=100)]
OfferState = Literal["active", "disabled", "removed"]


class OfferRow(BaseModel):
    offer_id: int
    share: Percent
    state: OfferState = "active"
    pinned: bool = False


def normalize(rows: list[OfferRow]) -> list[OfferRow]:
    active = [row for row in rows if row.state == "active"]
    free = [row for row in active if not row.pinned]
    remaining = 100 - sum(row.share for row in active if row.pinned)

    if not active:
        return rows
    if remaining < len(free) or (not free and remaining != 0):
        raise AppError(
            422, "Невозможно распределить 100% трафика. Открепите долю одного из офферов."
        )

    fixed = {row.offer_id: row.share for row in active if row.pinned}
    if free:
        quotient, remainder = divmod(remaining, len(free))
        fixed.update(
            (row.offer_id, quotient + (index < remainder)) for index, row in enumerate(free)
        )

    return [
        row.model_copy(update={"share": fixed[row.offer_id]}) if row.state == "active" else row
        for row in rows
    ]


def outbound(rows: list[OfferRow]) -> list[dict[str, object]]:
    return [
        row.model_dump(include={"offer_id", "share", "state"})
        for row in rows
        if row.state != "removed"
    ]


def matches_offers(left: list[OfferRow], right: list[OfferRow]) -> bool:
    return outbound(sorted(left, key=lambda row: row.offer_id)) == outbound(
        sorted(right, key=lambda row: row.offer_id)
    )


def merge_remote(previous: list[OfferRow], remote: list[OfferRow]) -> list[OfferRow]:
    old = {row.offer_id: row for row in previous}
    current = {row.offer_id for row in remote}
    result = [
        row.model_copy(
            update={"pinned": row.state == "active" and row.share > 0 and old[row.offer_id].pinned}
        )
        if row.offer_id in old
        else row
        for row in remote
    ]
    result.extend(
        row.model_copy(update={"state": "removed", "share": 0, "pinned": False})
        for row in previous
        if row.offer_id not in current
    )
    return result
