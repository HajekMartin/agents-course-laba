"""Search inputs and compact listing data reusable by marketplace providers."""

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SortOrder = Literal["relevance", "price_asc", "price_desc"]


class SearchRequest(BaseModel):
    """Validate search inputs before any HTTP request."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=256)
    min_price: int | None = Field(default=None, ge=0)
    max_price: int | None = Field(default=None, ge=0)
    location: str | None = Field(default=None, description="Czech postcode, e.g. 46001")
    radius_km: int | None = Field(default=None, ge=0, le=1000)
    sort_by: SortOrder = "relevance"
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("location")
    @classmethod
    def normalize_postcode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"[1-7][0-9]{2} ?[0-9]{2}", value):
            raise ValueError("location must be a Czech postcode, e.g. 46001 or 460 01")
        return value.replace(" ", "")

    @model_validator(mode="after")
    def validate_filters(self) -> Self:
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("min_price must not exceed max_price")
        if self.radius_km is not None and self.location is None:
            raise ValueError("radius_km requires a location postcode")
        return self


class Listing(BaseModel):
    """Only data needed by the search consumer; unknown values remain null."""

    title: str
    price: int | None
    currency: str = "CZK"
    location: str | None
    url: str
    description: str
