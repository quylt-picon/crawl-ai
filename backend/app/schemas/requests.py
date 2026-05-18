"""Request DTOs."""
from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl, field_validator


class CrawlSearchRequest(BaseModel):
    website_url: HttpUrl = Field(..., description="Website homepage URL")
    product_name: str = Field(..., min_length=1, max_length=300)
    product_code: str = Field(..., min_length=1, max_length=120)

    @field_validator("product_name", "product_code")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()
