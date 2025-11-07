from sqlalchemy import Column, String, TIMESTAMP, Integer
from server.core import Base


class URL(Base):
    __tablename__ = 'tbl_url'
    id = Column(String(36), primary_key=True)
    url = Column(String(1000), nullable=False, unique=True)
    short_url = Column(String(6), nullable=False)
    created_at = Column(TIMESTAMP, nullable=False)
    version = Column(Integer, nullable=False)