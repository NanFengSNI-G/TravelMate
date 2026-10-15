import time
import uuid
from sqlalchemy import String, Integer, JSON, Text, UniqueConstraint, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return str(uuid.uuid4())


def now():
    return int(time.time())


class Base(DeclarativeBase):
    pass


class Row:
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)


class User(Row, Base):
    __tablename__ = "users"
    name: Mapped[str] = mapped_column(String(80), unique=True)
    password: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="user")


class Conversation(Row, Base):
    __tablename__ = "conversations"
    owner: Mapped[str] = mapped_column(String(64), index=True)
    history: Mapped[list] = mapped_column(JSON, default=list)


class Resource(Row, Base):
    __tablename__ = "resources"
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    supplier: Mapped[str] = mapped_column(String(100))
    product: Mapped[str] = mapped_column(String(60))
    details: Mapped[dict] = mapped_column(JSON)
    price: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Inventory(Row, Base):
    __tablename__ = "inventory"
    resource: Mapped[str] = mapped_column(String(64))
    day: Mapped[str] = mapped_column(String(10))
    available: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("resource", "day"),)


class Quote(Row, Base):
    __tablename__ = "quotes"
    owner: Mapped[str] = mapped_column(String(64))
    resource: Mapped[str] = mapped_column(String(64))
    resource_version: Mapped[int] = mapped_column(Integer)
    revision: Mapped[str] = mapped_column(String(64))
    amount: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    slots: Mapped[list] = mapped_column(JSON)
    expires: Mapped[int] = mapped_column(Integer)


class Order(Row, Base):
    __tablename__ = "orders"
    owner: Mapped[str] = mapped_column(String(64), index=True)
    resource: Mapped[str] = mapped_column(String(64))
    revision: Mapped[str] = mapped_column(String(64))
    amount: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    slots: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="CONFIRMED")
    version: Mapped[int] = mapped_column(Integer, default=1)


class Proposal(Row, Base):
    __tablename__ = "proposals"
    owner: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    actions: Mapped[list] = mapped_column(JSON)
    evidence: Mapped[list] = mapped_column(JSON)
    expires: Mapped[int] = mapped_column(Integer)


class Operation(Row, Base):
    __tablename__ = "operations"
    proposal: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)


class Revision(Row, Base):
    __tablename__ = "knowledge_revisions"
    document: Mapped[str] = mapped_column(String(100), index=True)
    supplier: Mapped[str] = mapped_column(String(100))
    product: Mapped[str] = mapped_column(String(60))
    language: Mapped[str] = mapped_column(String(10), default="zh")
    valid_from: Mapped[str] = mapped_column(String(10))
    valid_to: Mapped[str] = mapped_column(String(10))
    original_valid_to: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20))
    digest: Mapped[str] = mapped_column(String(64))
    rules: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(200))
    error: Mapped[str] = mapped_column(Text, default="")


class Node(Row, Base):
    __tablename__ = "knowledge_nodes"
    revision: Mapped[str] = mapped_column(String(64), index=True)
    parent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    section: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)


class Plan(Row, Base):
    __tablename__ = "plans"
    owner: Mapped[str] = mapped_column(String(64))
    options: Mapped[list] = mapped_column(JSON)
    created: Mapped[int] = mapped_column(Integer, default=now)


class Case(Row, Base):
    __tablename__ = "support_cases"
    owner: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    context: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    assigned: Mapped[str | None] = mapped_column(String(64), nullable=True)
    replies: Mapped[list] = mapped_column(JSON, default=list)


class Run(Row, Base):
    __tablename__ = "runs"
    owner: Mapped[str] = mapped_column(String(64))
    conversation: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED")
    resume: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cancel_requested: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[int] = mapped_column(Integer, default=0)
    fence: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (Index("ix_runs_claim", "status", "lease_until"),)


class Event(Row, Base):
    __tablename__ = "run_events"
    run: Mapped[str] = mapped_column(String(64), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("run", "sequence"),)
