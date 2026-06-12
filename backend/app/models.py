"""Pydantic models shared across routes and the agent runner."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class User(BaseModel):
    user_id: str
    company_id: str
    email: str
    role: str          # admin | operator — action-level, carried but not a data gate
    access_scope: str  # energy | energy+financial — the financial data gate


class LoginUser(User):
    company_name: str


class Plant(BaseModel):
    id: int
    name: str
    nominal_power_kw: float | None
    region: str | None
    commissioning_date: str | None
    datasource_count: int


class RunCreate(BaseModel):
    prompt: str


class Run(BaseModel):
    run_id: UUID
    prompt: str
    status: str
    error: str | None
    created_at: datetime
    updated_at: datetime


class Document(BaseModel):
    id: UUID
    run_id: UUID | None
    filename: str
    doc_type: str
    created_at: datetime
