from pydantic import BaseModel, Field
from typing import Optional


class InventoryItemCreate(BaseModel):
    type: str  # resistor, capacitor, diode, LED, NPN_BJT, PNP_BJT, N_JFET, P_JFET, op_amp, potentiometer, switch
    value: float | None = None  # ohms, farads, etc.
    value_display: str = ""  # "10kΩ", "100nF"
    tolerance: str = "5%"
    package: str = "through-hole"
    voltage_rating: float | None = None
    current_rating_ma: float | None = None
    model: str | None = None  # e.g. "2N3904", "TL072"
    quantity: int = 1
    notes: str = ""
    buy_link: str = ""  # URL to purchase the part
    specs: dict = Field(default_factory=dict)  # datasheet electrical specs


class InventoryItem(InventoryItemCreate):
    id: str
