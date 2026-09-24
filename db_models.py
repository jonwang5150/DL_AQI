"""AQI 資料的 SQLAlchemy 2.x ORM 模型與 PostgreSQL 批次寫入。"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, Text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class AirQualityHourly(Base):
    __tablename__ = "air_quality_hourly"
    __table_args__ = {"schema": "public"}

    station: Mapped[str] = mapped_column(Text, primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), primary_key=True)
    aqi: Mapped[Decimal | None] = mapped_column(Numeric)
    air_quality_indicator: Mapped[str | None] = mapped_column(Text)
    o3: Mapped[Decimal | None] = mapped_column(Numeric)
    pm25: Mapped[Decimal | None] = mapped_column(Numeric)
    pm10: Mapped[Decimal | None] = mapped_column(Numeric)
    co: Mapped[Decimal | None] = mapped_column(Numeric)
    so2: Mapped[Decimal | None] = mapped_column(Numeric)
    no2: Mapped[Decimal | None] = mapped_column(Numeric)


def upsert_batch(session: Session, rows: list[dict]) -> None:
    if not rows:
        return
    # PostgreSQL 單一 INSERT 不可更新同一鍵兩次；保留每個鍵最後讀到的資料。
    unique = {(row["station"], row["observed_at"]): row for row in rows}
    values = list(unique.values())
    # 控制單次 SQL 的參數數量，即使使用者指定較大的 batch-size 也可執行。
    for offset in range(0, len(values), 1000):
        statement = insert(AirQualityHourly).values(values[offset:offset + 1000])
        statement = statement.on_conflict_do_update(
            index_elements=[AirQualityHourly.station, AirQualityHourly.observed_at],
            set_={
                column.name: statement.excluded[column.name]
                for column in AirQualityHourly.__table__.columns
                if not column.primary_key
            },
        )
        session.execute(statement)
