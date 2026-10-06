from typing import Optional

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


class ConfidenceInterval(BaseModel):
    lower: float
    upper: float


class ComparisonResult(BaseModel):
    variant: str
    control: str
    status: str
    method: Optional[str] = None
    p_value: Optional[float] = None
    adjusted_p_value: Optional[float] = None
    significant: Optional[bool] = None
    confidence_interval: Optional[ConfidenceInterval] = None
    required_users_per_group: Optional[int] = None
    additional_users_needed: Optional[int] = None
    estimated_days_needed: Optional[float] = None
    warnings: list[str] = Field(default_factory=list)


class ZeroConversionWarning(BaseModel):
    variant: str
    message: str


class SignificanceOut(BaseModel):
    alpha: float
    comparisons: list[ComparisonResult]
    zero_conversion_warnings: list[ZeroConversionWarning]


class ResultsOut(BaseModel):
    variants: list[ResultVariant]
    significance: SignificanceOut
