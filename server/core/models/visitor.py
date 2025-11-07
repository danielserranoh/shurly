from sqlalchemy import Column, UUID, String, ForeignKey, TIMESTAMP, Integer
from sqlalchemy.orm import relationship
from server.core import Base


class Visitor(Base):
    __tablename__ = 'tbl_visitor'
    id = Column(String(36), primary_key=True)
    url_id = Column(String(36), ForeignKey('tbl_url.id'), nullable=False)
    ip = Column(String(50), nullable=False)
    country = Column(String(100), nullable=False)
    created_at = Column(TIMESTAMP, nullable=False)
    version = Column(Integer, nullable=False)
    url = relationship("URL", backref="visitors")