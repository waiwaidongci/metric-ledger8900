from sqlalchemy import ForeignKey,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from ..config.database import Base
from ..utils.clock import now
class MetricVersion(Base):
    __tablename__="metric_versions"
    id: Mapped[int]=mapped_column(primary_key=True)
    note: Mapped[str]
    published_by: Mapped[str]
    published_at: Mapped[str]=mapped_column(default=now)
class MetricDefinition(Base):
    __tablename__="metric_definitions"
    __table_args__=(UniqueConstraint("version_id","key"),)
    id: Mapped[int]=mapped_column(primary_key=True)
    version_id: Mapped[int]=mapped_column(ForeignKey("metric_versions.id"))
    position: Mapped[int]
    key: Mapped[str]
    name: Mapped[str]
    expression: Mapped[str]
    unit: Mapped[str]
    description: Mapped[str]
