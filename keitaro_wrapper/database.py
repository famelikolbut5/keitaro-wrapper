from sqlalchemy import JSON, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class StreamState(Base):
    __tablename__ = "stream_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    campaign_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String)
    schema: Mapped[str] = mapped_column(String)
    published: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    draft: Mapped[list[dict[str, object]] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    conflict: Mapped[bool]
    revision: Mapped[int]


def create_sessions(url: str) -> sessionmaker[Session]:
    engine = create_engine(url)
    return sessionmaker(engine, expire_on_commit=False)
