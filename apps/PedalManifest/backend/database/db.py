"""
SQLite database for component inventory and design history (keepers).
"""

import aiosqlite
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent.parent.parent / "pedalforge.db"


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    db = await get_db()
    try:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS inventory (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                value REAL,
                value_display TEXT DEFAULT '',
                tolerance TEXT DEFAULT '5%',
                package TEXT DEFAULT 'through-hole',
                voltage_rating REAL,
                current_rating_ma REAL,
                model TEXT,
                quantity INTEGER DEFAULT 1,
                notes TEXT DEFAULT '',
                buy_link TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_inventory_type ON inventory(type);
            CREATE INDEX IF NOT EXISTS idx_inventory_value ON inventory(value);

            CREATE TABLE IF NOT EXISTS keepers (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                name TEXT NOT NULL,
                intent_description TEXT DEFAULT '',
                transform_plan TEXT DEFAULT '{}',
                circuit_graph TEXT DEFAULT '{}',
                spice_netlist TEXT DEFAULT '',
                parameter_state TEXT DEFAULT '{}',
                simulation_results TEXT DEFAULT '{}',
                inventory_status TEXT DEFAULT '{}',
                dsp_model_state TEXT DEFAULT '{}'
            );
        """)
        await db.commit()
        # Migrations: add columns to existing databases
        for col_sql in [
            "ALTER TABLE inventory ADD COLUMN buy_link TEXT DEFAULT ''",
            "ALTER TABLE inventory ADD COLUMN specs TEXT DEFAULT '{}'",
        ]:
            try:
                await db.execute(col_sql)
                await db.commit()
            except Exception:
                pass  # Column already exists
    finally:
        await db.close()


def _deserialise_item(row: dict) -> dict:
    """Parse JSON fields in an inventory row."""
    specs = row.get("specs")
    if isinstance(specs, str):
        try:
            row["specs"] = json.loads(specs)
        except Exception:
            row["specs"] = {}
    elif specs is None:
        row["specs"] = {}
    return row


# --- Inventory CRUD ---

async def create_inventory_item(item: dict) -> dict:
    db = await get_db()
    try:
        item_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        specs = item.get("specs", {})
        if isinstance(specs, dict):
            specs = json.dumps(specs)
        await db.execute(
            """INSERT INTO inventory (id, type, value, value_display, tolerance, package,
               voltage_rating, current_rating_ma, model, quantity, notes, buy_link,
               specs, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item_id, item["type"], item.get("value"), item.get("value_display", ""),
             item.get("tolerance", "5%"), item.get("package", "through-hole"),
             item.get("voltage_rating"), item.get("current_rating_ma"),
             item.get("model"), item.get("quantity", 1), item.get("notes", ""),
             item.get("buy_link", ""), specs, now, now)
        )
        await db.commit()
        return {**item, "id": item_id}
    finally:
        await db.close()


async def get_inventory_items(
    type_filter: Optional[str] = None,
    search: Optional[str] = None,
) -> list[dict]:
    db = await get_db()
    try:
        query = "SELECT * FROM inventory WHERE 1=1"
        params = []
        if type_filter:
            query += " AND type = ?"
            params.append(type_filter)
        if search:
            query += " AND (value_display LIKE ? OR model LIKE ? OR notes LIKE ?)"
            params.extend([f"%{search}%"] * 3)
        query += " ORDER BY type, value"
        rows = await db.execute_fetchall(query, params)
        return [_deserialise_item(dict(row)) for row in rows]
    finally:
        await db.close()


async def get_inventory_item(item_id: str) -> Optional[dict]:
    db = await get_db()
    try:
        row = await db.execute_fetchall(
            "SELECT * FROM inventory WHERE id = ?", (item_id,)
        )
        return _deserialise_item(dict(row[0])) if row else None
    finally:
        await db.close()


async def update_inventory_item(item_id: str, updates: dict) -> Optional[dict]:
    db = await get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        fields = []
        values = []
        for key, val in updates.items():
            if key not in ("id", "created_at"):
                fields.append(f"{key} = ?")
                values.append(val)
        fields.append("updated_at = ?")
        values.append(now)
        values.append(item_id)
        await db.execute(
            f"UPDATE inventory SET {', '.join(fields)} WHERE id = ?",
            values
        )
        await db.commit()
        return await get_inventory_item(item_id)
    finally:
        await db.close()


async def delete_inventory_item(item_id: str) -> bool:
    db = await get_db()
    try:
        cursor = await db.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def get_inventory_by_type(component_type: str) -> list[dict]:
    """Get all inventory items of a given type, for the compiler."""
    return await get_inventory_items(type_filter=component_type)


async def get_inventory_values(component_type: str) -> list[float]:
    """Get all available values for a component type."""
    items = await get_inventory_by_type(component_type)
    return [item["value"] for item in items if item.get("value") is not None]


# --- Keeper CRUD ---

async def create_keeper(keeper: dict) -> dict:
    db = await get_db()
    try:
        keeper_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            """INSERT INTO keepers (id, timestamp, name, intent_description, transform_plan,
               circuit_graph, spice_netlist, parameter_state, simulation_results,
               inventory_status, dsp_model_state)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (keeper_id, now, keeper["name"], keeper.get("intent_description", ""),
             json.dumps(keeper.get("transform_plan", {})),
             json.dumps(keeper.get("circuit_graph", {})),
             keeper.get("spice_netlist", ""),
             json.dumps(keeper.get("parameter_state", {})),
             json.dumps(keeper.get("simulation_results", {})),
             json.dumps(keeper.get("inventory_status", {})),
             json.dumps(keeper.get("dsp_model_state", {})))
        )
        await db.commit()
        return {**keeper, "id": keeper_id, "timestamp": now}
    finally:
        await db.close()


async def get_keepers() -> list[dict]:
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT * FROM keepers ORDER BY timestamp DESC"
        )
        result = []
        for row in rows:
            d = dict(row)
            for json_field in ("transform_plan", "circuit_graph", "parameter_state",
                               "simulation_results", "inventory_status", "dsp_model_state"):
                if isinstance(d.get(json_field), str):
                    d[json_field] = json.loads(d[json_field])
            result.append(d)
        return result
    finally:
        await db.close()


async def get_keeper(keeper_id: str) -> Optional[dict]:
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT * FROM keepers WHERE id = ?", (keeper_id,)
        )
        if not rows:
            return None
        d = dict(rows[0])
        for json_field in ("transform_plan", "circuit_graph", "parameter_state",
                           "simulation_results", "inventory_status", "dsp_model_state"):
            if isinstance(d.get(json_field), str):
                d[json_field] = json.loads(d[json_field])
        return d
    finally:
        await db.close()


async def delete_keeper(keeper_id: str) -> bool:
    db = await get_db()
    try:
        cursor = await db.execute("DELETE FROM keepers WHERE id = ?", (keeper_id,))
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()
