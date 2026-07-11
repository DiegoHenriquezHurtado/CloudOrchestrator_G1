import datetime
from sqlalchemy.orm import declarative_base, Mapped, mapped_column
from sqlalchemy import Integer, String, DECIMAL, TIMESTAMP, text, ForeignKey

Base = declarative_base()

class Worker(Base):
    __tablename__ = "workers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hostname: Mapped[str] = mapped_column(String(50), nullable=False)
    ip_management: Mapped[str] = mapped_column(String(15), nullable=False)
    total_ram: Mapped[int] = mapped_column(Integer, nullable=False)
    total_cpu: Mapped[int] = mapped_column(Integer, nullable=False)
    current_cpu_load: Mapped[float] = mapped_column(DECIMAL(5, 2), default=0.0)
    current_ram_available: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="ALIVE")
    cluster_type: Mapped[str] = mapped_column(String(20), default="linux")
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP")
    )

# Models for role visibility
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="STUDENT")
    admin_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)

class Slice(Base):
    __tablename__ = "slices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    
class VirtualMachine(Base):
    __tablename__ = "virtual_machines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slice_id: Mapped[int] = mapped_column(Integer, ForeignKey("slices.id", ondelete="CASCADE"))
    worker_id: Mapped[int] = mapped_column(Integer, ForeignKey("workers.id"), nullable=True)
