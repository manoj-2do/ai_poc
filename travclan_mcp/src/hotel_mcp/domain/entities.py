from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Occupancy(BaseModel):
    num_of_adults: int = Field(alias="numOfAdults", ge=1)
    child_ages: list[int] = Field(default_factory=list, alias="childAges")

    model_config = {"populate_by_name": True}


class SearchCriteria(BaseModel):
    check_in: str = Field(alias="checkIn")
    check_out: str = Field(alias="checkOut")
    occupancies: list[Occupancy] = Field(min_length=1)
    location_id: str | None = Field(default=None, alias="locationId")
    hotel_id: str | None = Field(default=None, alias="hotelId")
    nationality: str = "IN"
    page: int = Field(default=1, ge=1)
    trace_id: str | None = Field(default=None, alias="traceId")

    model_config = {"populate_by_name": True}


class GuestDetails(BaseModel):
    title: str
    first_name: str = Field(alias="firstName")
    last_name: str = Field(alias="lastName")
    is_lead_guest: bool = Field(alias="isLeadGuest")
    type: Literal["adult", "child"]
    middle_name: str | None = Field(default=None, alias="middleName")
    email: str | None = None
    isd_code: str | None = Field(default=None, alias="isdCode")
    contact_number: str | None = Field(default=None, alias="contactNumber")
    age: int | None = None

    model_config = {"populate_by_name": True}


class RoomSelection(BaseModel):
    room_id: str = Field(alias="roomId")
    guests: list[GuestDetails] = Field(min_length=1)

    model_config = {"populate_by_name": True}


class BookingRequest(BaseModel):
    option_id: str = Field(alias="optionId")
    trace_id: str = Field(alias="traceId")
    room_details: list[RoomSelection] = Field(alias="roomDetails", min_length=1)
    hotel_id: str | None = Field(default=None, alias="hotelId")
    special_requests: str | None = Field(default=None, alias="specialRequests")

    model_config = {"populate_by_name": True}


class PriceCheckCriteria(BaseModel):
    trace_id: str = Field(alias="traceId")
    hotel_id: str = Field(alias="hotelId")
    option_id: str = Field(alias="optionId")

    model_config = {"populate_by_name": True}
