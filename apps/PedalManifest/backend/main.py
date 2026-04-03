"""
PedalForge — Main FastAPI application.
"""

import json
import pathlib
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.database.db import (
    init_db, create_inventory_item, get_inventory_items, get_inventory_item,
    update_inventory_item, delete_inventory_item, get_inventory_values,
    create_keeper, get_keepers, get_keeper, delete_keeper,
)
from backend.models.design_intent import DesignIntent
from backend.models.transform_plan import TransformPlan
from backend.models.inventory import InventoryItemCreate
from backend.models.keeper import KeeperCreate
from backend.engine.transform_planner import plan_transforms
from backend.engine.block_compiler import compile_circuit
from backend.engine.spice_generator import generate_netlist, run_ngspice
from backend.engine.dsp_engine import (
    AudioEngine, AudioConfig, build_dsp_chain_from_plan, DSPChain,
)
from backend.physics import component_db as cdb
from backend.physics.datasheet_lookup import fetch as fetch_datasheet
from backend.physics.operating_point import verify_circuit

from backend.ai.ollama_client import (
    check_ollama_available, get_available_models, parse_intent,
    explain_results, recommend_purchases,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    if audio_engine.is_running:
        audio_engine.stop()


app = FastAPI(title="PedalManifest", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global audio engine
audio_engine = AudioEngine()

# Conversation history for AI context
conversation_history: list[dict] = []

# Current design state
current_design: dict = {
    "intent": None,
    "plan": None,
    "circuit": None,
    "netlist": None,
    "simulation": None,
    "dsp_chain": None,
}


# ============================================================
# Health / Status
# ============================================================

@app.get("/api/status")
async def get_status():
    ollama_ok = await check_ollama_available()
    return {
        "ollama_available": ollama_ok,
        "audio_running": audio_engine.is_running,
        "has_design": current_design["circuit"] is not None,
    }


# ============================================================
# AI / Chat
# ============================================================

class ChatMessage(BaseModel):
    message: str
    model: str = "qwen3:14b"


@app.post("/api/chat")
async def chat(msg: ChatMessage):
    global conversation_history, current_design

    # Parse intent
    intent_dict = await parse_intent(msg.message, msg.model, conversation_history)

    if "error" in intent_dict:
        return {
            "response": f"I had trouble understanding that: {intent_dict['error']}",
            "intent": None,
            "plan": None,
        }

    # Track conversation
    conversation_history.append({"role": "user", "content": msg.message})

    # Build DesignIntent
    intent = DesignIntent(**intent_dict, raw_input=msg.message)
    current_design["intent"] = intent.model_dump()

    # Plan transforms
    plan = plan_transforms(intent)
    current_design["plan"] = plan.model_dump()

    # Get inventory for compilation
    inventory_values = await _get_inventory_map()

    # Compile circuit
    circuit = compile_circuit(plan, inventory_values, intent.constraints.supply_voltage)
    current_design["circuit"] = circuit.model_dump()

    # Physics: operating point verification (before SPICE — catches obvious errors fast)
    circuit_dict = circuit.model_dump()
    op_specs = {}
    for comp in circuit.components:
        if comp.model and comp.type in ("NPN_BJT", "PNP_BJT", "N_JFET", "P_JFET", "op_amp"):
            local = cdb.lookup(comp.model)
            if local:
                op_specs[comp.model] = local
    op_check = verify_circuit(circuit_dict, intent.constraints.supply_voltage, op_specs)
    current_design["op_check"] = op_check

    # Generate SPICE netlist
    netlist = generate_netlist(circuit)
    current_design["netlist"] = netlist

    # Run SPICE validation
    sim_results = run_ngspice(netlist)
    current_design["simulation"] = sim_results

    # Build DSP chain
    dsp_stages = []
    for i, stage in enumerate(plan.stages):
        dsp_stages.append({
            "transform": stage.transform,
            "params": stage.params,
            "stage_index": i,
        })
    dsp_chain = build_dsp_chain_from_plan(dsp_stages, audio_engine.config.sample_rate)
    audio_engine.dsp_chain = dsp_chain

    # Generate AI explanation
    explanation = ""
    if sim_results.get("success"):
        circuit_desc = f"{len(plan.stages)} stage pedal: {' → '.join(s.transform for s in plan.stages)}"
        explanation = await explain_results(sim_results, circuit_desc, msg.model)
    else:
        explanation = "Circuit designed but SPICE validation had issues. You can still play through the DSP model."
        if sim_results.get("error"):
            explanation += f" ({sim_results['error']})"

    # Check inventory status
    total = len(circuit.components)
    in_stock = sum(1 for c in circuit.components if c.in_inventory)
    missing = [f"{c.value_display} {c.type} ({c.role})" for c in circuit.components if not c.in_inventory and c.type in ("resistor", "capacitor", "diode", "LED", "NPN_BJT", "PNP_BJT", "N_JFET", "op_amp")]

    inventory_note = ""
    if missing:
        inventory_note = f"\n\n📦 {in_stock}/{total} components in stock. Missing: {', '.join(missing[:5])}"
        if len(missing) > 5:
            inventory_note += f" (+{len(missing)-5} more)"

    conversation_history.append({"role": "assistant", "content": explanation})

    return {
        "response": explanation + inventory_note,
        "intent": current_design["intent"],
        "plan": current_design["plan"],
        "circuit": current_design["circuit"],
        "simulation": sim_results,
        "op_check": op_check,
        "pots": circuit.pots,
    }


@app.get("/api/ai/models")
async def list_ai_models():
    models = await get_available_models()
    return {"models": models}


# ============================================================
# Audio Engine
# ============================================================

@app.get("/api/audio/devices")
async def list_audio_devices():
    return {"devices": AudioEngine.list_devices()}


class AudioConfigRequest(BaseModel):
    input_device: Optional[int] = None
    output_device: Optional[int] = None
    sample_rate: int = 48000
    buffer_size: int = 256


@app.post("/api/audio/configure")
async def configure_audio(config: AudioConfigRequest):
    audio_engine.configure(AudioConfig(
        input_device=config.input_device,
        output_device=config.output_device,
        sample_rate=config.sample_rate,
        buffer_size=config.buffer_size,
    ))
    return {"status": "configured"}


@app.post("/api/audio/start")
async def start_audio():
    try:
        audio_engine.start()
        return {"status": "running"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/audio/stop")
async def stop_audio():
    audio_engine.stop()
    return {"status": "stopped"}


@app.get("/api/audio/status")
async def audio_status():
    return {
        "running": audio_engine.is_running,
        "bypass": audio_engine.dsp_chain.bypass,
        "input_level": audio_engine.input_level,
        "output_level": audio_engine.output_level,
    }


@app.post("/api/audio/bypass")
async def toggle_bypass(enabled: bool = True):
    audio_engine.dsp_chain.bypass = enabled
    return {"bypass": enabled}


# ============================================================
# Knob / Parameter Control
# ============================================================

class KnobUpdate(BaseModel):
    stage_index: int
    param_name: str
    value: float


@app.post("/api/knob")
async def update_knob(update: KnobUpdate):
    audio_engine.dsp_chain.update_param(
        update.stage_index, update.param_name, update.value
    )
    return {"status": "updated"}


# ============================================================
# Inventory
# ============================================================

@app.get("/api/inventory")
async def list_inventory(type: Optional[str] = None, search: Optional[str] = None):
    items = await get_inventory_items(type_filter=type, search=search)
    return {"items": items}


@app.post("/api/inventory")
async def add_inventory_item(item: InventoryItemCreate):
    created = await create_inventory_item(item.model_dump())
    return created


@app.get("/api/inventory/{item_id}")
async def get_inventory_item_by_id(item_id: str):
    item = await get_inventory_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@app.put("/api/inventory/{item_id}")
async def update_inventory(item_id: str, updates: dict):
    item = await update_inventory_item(item_id, updates)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@app.delete("/api/inventory/{item_id}")
async def remove_inventory_item(item_id: str):
    deleted = await delete_inventory_item(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"status": "deleted"}


@app.patch("/api/inventory/{item_id}/quantity")
async def adjust_quantity(item_id: str, delta: int = Query(...)):
    item = await get_inventory_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    new_qty = max(0, item["quantity"] + delta)
    updated = await update_inventory_item(item_id, {"quantity": new_qty})
    return updated


# ============================================================
# Keepers / Design History
# ============================================================

@app.get("/api/keepers")
async def list_keepers():
    keepers = await get_keepers()
    return {"keepers": keepers}


@app.post("/api/keepers")
async def save_keeper(keeper: KeeperCreate):
    # Merge current design state
    keeper_data = keeper.model_dump()
    if current_design["plan"]:
        keeper_data["transform_plan"] = current_design["plan"]
    if current_design["circuit"]:
        keeper_data["circuit_graph"] = current_design["circuit"]
    if current_design["netlist"]:
        keeper_data["spice_netlist"] = current_design["netlist"]
    if current_design["simulation"]:
        keeper_data["simulation_results"] = current_design["simulation"]

    created = await create_keeper(keeper_data)
    return created


@app.get("/api/keepers/{keeper_id}")
async def get_keeper_by_id(keeper_id: str):
    keeper = await get_keeper(keeper_id)
    if not keeper:
        raise HTTPException(status_code=404, detail="Keeper not found")
    return keeper


@app.delete("/api/keepers/{keeper_id}")
async def remove_keeper(keeper_id: str):
    deleted = await delete_keeper(keeper_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Keeper not found")
    return {"status": "deleted"}


@app.post("/api/keepers/{keeper_id}/load")
async def load_keeper(keeper_id: str):
    """Load a keeper design back into the active state."""
    keeper = await get_keeper(keeper_id)
    if not keeper:
        raise HTTPException(status_code=404, detail="Keeper not found")

    current_design["plan"] = keeper.get("transform_plan")
    current_design["circuit"] = keeper.get("circuit_graph")
    current_design["netlist"] = keeper.get("spice_netlist")
    current_design["simulation"] = keeper.get("simulation_results")

    # Rebuild DSP chain from plan
    if keeper.get("transform_plan") and "stages" in keeper["transform_plan"]:
        dsp_stages = []
        for i, stage in enumerate(keeper["transform_plan"]["stages"]):
            dsp_stages.append({
                "transform": stage["transform"],
                "params": stage.get("params", {}),
                "stage_index": i,
            })
        dsp_chain = build_dsp_chain_from_plan(dsp_stages, audio_engine.config.sample_rate)
        audio_engine.dsp_chain = dsp_chain

    return {"status": "loaded", "keeper": keeper}


# ============================================================
# Current Design State
# ============================================================

@app.get("/api/design")
async def get_current_design():
    return current_design


@app.get("/api/design/netlist")
async def get_netlist():
    return {"netlist": current_design.get("netlist", "")}


# ============================================================
# Physics / Component Database
# ============================================================

@app.get("/api/physics/lookup/{part_number}")
async def physics_lookup(part_number: str):
    """Look up full datasheet specs for a component by part number.

    Returns local DB data instantly; falls back to LCSC web search for
    unknown parts.  Always returns a JSON object — check 'found' field.
    """
    result = await fetch_datasheet(part_number)
    return result


@app.get("/api/physics/search")
async def physics_search(
    q: str = Query(""),
    type: Optional[str] = Query(None),
    material: Optional[str] = Query(None),
    limit: int = Query(30),
):
    """Search the local component database."""
    results = cdb.search(query=q, type_filter=type, material=material, limit=limit)
    return {"results": results, "count": len(results)}


@app.get("/api/physics/substitutes/{part_number}")
async def physics_substitutes(part_number: str, relax: bool = False):
    """Return substitute parts for a given component."""
    subs = cdb.suggest_substitutes(part_number, relax_ratings=relax)
    return {"substitutes": subs}


class VerifyCircuitRequest(BaseModel):
    circuit_graph: dict
    supply_voltage: float = 9.0
    component_specs: dict = {}  # part_number → specs; auto-fetched if empty


@app.post("/api/physics/verify")
async def physics_verify(req: VerifyCircuitRequest):
    """Run operating point checks on a compiled circuit graph."""
    specs = req.component_specs
    # Auto-populate specs for active devices from local DB if not provided
    if not specs:
        for comp in req.circuit_graph.get("components", []):
            model = comp.get("model")
            if model and comp.get("type") in (
                "NPN_BJT", "PNP_BJT", "N_JFET", "P_JFET", "op_amp"
            ):
                local = cdb.lookup(model)
                if local:
                    specs[model] = local
    result = verify_circuit(req.circuit_graph, req.supply_voltage, specs)
    return result


# ============================================================
# Helpers
# ============================================================

async def _get_inventory_map() -> dict[str, list[float]]:
    """Build a map of component types to available values from inventory."""
    result = {}
    for comp_type in ("resistor", "capacitor", "diode", "LED", "NPN_BJT", "PNP_BJT",
                      "N_JFET", "P_JFET", "op_amp", "potentiometer"):
        values = await get_inventory_values(comp_type)
        if values:
            result[comp_type] = values
    return result


# ============================================================
# SPA Static File Serving (must be last — catches all non-API routes)
# ============================================================

_STATIC_DIR = pathlib.Path(__file__).parent.parent / "static"


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    candidate = _STATIC_DIR / full_path
    if candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(_STATIC_DIR / "index.html")
