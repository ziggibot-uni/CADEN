"""
Ollama Client — Local AI integration for intent parsing and explanation.
Uses a 7B parameter model running via Ollama.
"""

import json
import httpx
from typing import Optional

OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:14b"

INTENT_SYSTEM_PROMPT = """You are a guitar pedal circuit design assistant. Your ONLY job is to parse the user's
natural language description of a desired guitar effect into a structured JSON object.

You must output ONLY valid JSON matching this schema:
{
  "transforms": ["list of transform types"],
  "character": ["list of sound character descriptors"],
  "constraints": {
    "supply_voltage": 9,
    "current_draw_max_ma": 10,
    "input_impedance_kohm": 500,
    "output_impedance_ohm": 100,
    "component_series": "E24"
  },
  "reference_sounds": ["list of reference pedal names"],
  "avoid": ["list of things to avoid"]
}

Valid transform types:
- gain_clean, gain_soft_clip, gain_hard_clip, gain_asymmetric, gain_fuzz
- filter_lp, filter_hp, filter_bp, filter_notch, filter_tonestack
- compress
- modulate_tremolo, modulate_vibrato, modulate_chorus

Valid character descriptors:
- warm, bright, dark, thick, thin, aggressive, smooth, sputtery, gated
- asymmetric, vintage, modern, compressed, open, creamy, crunchy, fuzzy, clean

Valid reference sounds:
- tube screamer, ts808, rat, big muff, fuzz face, klon, blues breaker, boss ds-1
- mxr distortion+, tone bender

Output ONLY the JSON. No explanation, no markdown, no extra text."""

EXPLAIN_SYSTEM_PROMPT = """You are a guitar pedal design assistant. Given simulation results
for a circuit, explain them in plain English for a guitar player. Be concise and practical.
Focus on what the pedal will sound like and how the controls interact.
Keep your response under 3 sentences."""

RECOMMEND_SYSTEM_PROMPT = """You are a guitar pedal component advisor. Given a user's current
component inventory and a circuit design that needs parts they don't have, suggest the most
cost-effective purchases that would unlock the most new circuit possibilities.
Keep suggestions to 3 items max. Be specific about part numbers and approximate cost.
Keep your response under 4 sentences."""


async def check_ollama_available() -> bool:
    """Check if Ollama is running and accessible."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags", timeout=5.0)
            return resp.status_code == 200
    except Exception:
        return False


async def get_available_models() -> list[str]:
    """Get list of models available in Ollama."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
    except Exception:
        pass
    return []


async def parse_intent(user_input: str, model: str = DEFAULT_MODEL,
                       conversation_history: Optional[list[dict]] = None) -> dict:
    """
    Parse natural language into a DesignIntent JSON.
    Returns the parsed dict or an error dict.
    """
    messages = [{"role": "system", "content": INTENT_SYSTEM_PROMPT}]

    # Add conversation history for context
    if conversation_history:
        for msg in conversation_history[-6:]:  # Last 6 messages for context
            messages.append(msg)

    messages.append({"role": "user", "content": user_input})

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,  # Low temp for structured output
                        "num_predict": 500,
                    },
                },
                timeout=60.0,
            )

            if resp.status_code != 200:
                return {"error": f"Ollama returned status {resp.status_code}"}

            data = resp.json()
            content = data.get("message", {}).get("content", "")

            # Try to parse JSON from response
            return _extract_json(content)

    except httpx.TimeoutException:
        return {"error": "Ollama request timed out. Is the model loaded?"}
    except httpx.ConnectError:
        return {"error": "Cannot connect to Ollama. Make sure it's running (ollama serve)."}
    except Exception as e:
        return {"error": f"Ollama error: {str(e)}"}


async def explain_results(simulation_results: dict, circuit_description: str,
                          model: str = DEFAULT_MODEL) -> str:
    """Generate a plain-English explanation of simulation results."""
    prompt = f"""Circuit: {circuit_description}

Simulation Results:
- Gain at 1kHz: {simulation_results.get('gain_1khz_db', 'N/A')} dB
- Low -3dB frequency: {simulation_results.get('f_low_3db_hz', 'N/A')} Hz
- High -3dB frequency: {simulation_results.get('f_high_3db_hz', 'N/A')} Hz
- Current draw: {simulation_results.get('current_draw_ma', 'N/A')} mA

Explain what this pedal will sound like."""

    return await _chat(prompt, EXPLAIN_SYSTEM_PROMPT, model)


async def recommend_purchases(inventory_summary: str, missing_components: list[str],
                              model: str = DEFAULT_MODEL) -> str:
    """Generate purchase recommendations based on inventory gaps."""
    prompt = f"""Current inventory summary: {inventory_summary}

Components needed for current design that are missing:
{chr(10).join(f'- {c}' for c in missing_components)}

What should the user buy to get the most value?"""

    return await _chat(prompt, RECOMMEND_SYSTEM_PROMPT, model)


async def _chat(prompt: str, system_prompt: str, model: str) -> str:
    """Generic chat completion."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 300},
                },
                timeout=60.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("message", {}).get("content", "No response")
    except Exception as e:
        return f"AI unavailable: {str(e)}"
    return "AI unavailable"


def _extract_json(text: str) -> dict:
    """Extract JSON from a model response that might contain extra text."""
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON block in markdown
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        try:
            return json.loads(text[start:end].strip())
        except (json.JSONDecodeError, ValueError):
            pass

    # Try to find anything that looks like JSON
    for i, char in enumerate(text):
        if char == "{":
            # Find matching closing brace
            depth = 0
            for j in range(i, len(text)):
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[i:j+1])
                        except json.JSONDecodeError:
                            break
            break

    return {"error": "Could not parse AI response as JSON. Please rephrase your request."}
