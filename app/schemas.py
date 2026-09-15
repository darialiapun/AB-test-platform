from pydantic import BaseModel, Field


class VariantIn(BaseModel):
    name: str
    weight: int = Field(ge=0, le=100)


class ExperimentCreate(BaseModel):
    name: str
    variants: list[VariantIn]


class ExperimentOut(BaseModel):
    id: str
    name: str
    variants: list[VariantIn]
    status: str


class VariantOut(BaseModel):
    experiment_id: str
    user_id: str
    variant: str


class EventIn(BaseModel):
    experiment_id: str
    user_id: str
    event_type: str


class EventOut(BaseModel):
    status: str


class ResultVariant(BaseModel):
    name: str
    users: int
    conversions: int
    conversion_rate: float


class ResultsOut(BaseModel):
    variants: list[ResultVariant]
