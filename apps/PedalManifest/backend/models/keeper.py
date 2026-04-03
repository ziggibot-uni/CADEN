from pydantic import BaseModel, Field
from typing import Any, Optional
from .transform_plan import TransformPlan
from .circuit import CircuitGraph


class SimulationResults(BaseModel):
    gain_1khz_db: float | None = None
    f_low_3db_hz: float | None = None
    f_high_3db_hz: float | None = None
    current_draw_ma: float | None = None
    thd_1khz_percent: float | None = None
    clipping_threshold_v: float | None = None
    frequency_response: list[dict[str, float]] = Field(default_factory=list)


class InventoryStatus(BaseModel):
    all_in_stock: bool = False
    missing_components: list[str] = Field(default_factory=list)
    total_components: int = 0
    in_stock_count: int = 0


class KeeperCreate(BaseModel):
    name: str
    intent_description: str = ""
    transform_plan: dict[str, Any] = Field(default_factory=dict)
    circuit_graph: dict[str, Any] = Field(default_factory=dict)
    spice_netlist: str = ""
    parameter_state: dict[str, float] = Field(default_factory=dict)
    simulation_results: dict[str, Any] = Field(default_factory=dict)
    inventory_status: dict[str, Any] = Field(default_factory=dict)
    dsp_model_state: dict[str, Any] = Field(default_factory=dict)


class KeeperDesign(KeeperCreate):
    id: str
    timestamp: str
