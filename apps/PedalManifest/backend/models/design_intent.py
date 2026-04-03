from pydantic import BaseModel, Field
from typing import Optional


class DesignConstraints(BaseModel):
    supply_voltage: float = 9.0
    current_draw_max_ma: float = 10.0
    input_impedance_kohm: float = 500.0
    output_impedance_ohm: float = 100.0
    component_series: str = "E24"


class DesignIntent(BaseModel):
    transforms: list[str] = Field(default_factory=list)
    character: list[str] = Field(default_factory=list)
    constraints: DesignConstraints = Field(default_factory=DesignConstraints)
    reference_sounds: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    raw_input: Optional[str] = None
