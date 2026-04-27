import datetime

from sqlalchemy import ForeignKey, String, Integer, DateTime
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped


class BaseModel(DeclarativeBase):
    pass


class NoticeCategory(BaseModel):
    __tablename__ = 'notice_category'
    category_id: Mapped[int] = mapped_column(Integer, nullable=False, primary_key=True)
    category_name: Mapped[str] = mapped_column(String(20), nullable=False)


class Notice(BaseModel):
    __tablename__ = 'notices'
    notice_id: Mapped[int] = mapped_column(Integer, nullable=False, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(200), nullable=False)
    expired_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    category_id: Mapped[int] = mapped_column(ForeignKey('notice_category.category_id'), nullable=False)
    user_id: Mapped[str] = mapped_column(String(20), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
