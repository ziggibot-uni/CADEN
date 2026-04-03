from pydantic import BaseModel, Field
from typing import Any


class CircuitComponent(BaseModel):
    id: str  # namespaced, e.g. S1_R1
    type: str  # resistor, capacitor, NPN_BJT, etc.
    value: float | None = None  # ohms, farads, etc.
    value_display: str = ""  # "10kΩ", "100nF", etc.
    model: str | None = None  # for semiconductors
    role: str = ""
    nodes: list[str] = Field(default_factory=list)  # connected node names
    voltage_rating: float | None = None
    in_inventory: bool = False
    inventory_item_id: str | None = None


class CircuitNode(BaseModel):
    name: str
    connections: list[str] = Field(default_factory=list)  # component IDs


class StageInfo(BaseModel):
    stage_index: int
    block_id: str
    transform: str
    params: dict[str, Any] = Field(default_factory=dict)
    components: list[str] = Field(default_factory=list)  # component IDs in this stage
    spice_template: str = ""  # raw SPICE template from block JSON
    component_values: dict[str, Any] = Field(default_factory=dict)  # e.g. {"Rc": 4700, "Re": 470}
    node_map: dict[str, str] = Field(default_factory=dict)  # e.g. {"in": "S1_in", "out": "S1_out"}


class CircuitGraph(BaseModel):
    components: list[CircuitComponent] = Field(default_factory=list)
    nodes: dict[str, CircuitNode] = Field(default_factory=dict)
    stages: list[StageInfo] = Field(default_factory=list)
    terminals: dict[str, str] = Field(default_factory=lambda: {
        "GND": "gnd",
        "9V": "vcc",
        "IN": "input",
        "OUT": "output",
    })
    pots: list[dict[str, Any]] = Field(default_factory=list)
    switches: list[dict[str, Any]] = Field(default_factory=list)
