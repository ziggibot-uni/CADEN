# PedalForge — Project Specification

## Premise

Guitar pedal circuits are a closed, physics-governed domain. Every effect that can be applied to a guitar signal maps to a known set of analog circuit transformations. These transformations are deterministic — resistor values, capacitor sizes, transistor choices, and topology all follow physical laws, not guesses.

This project builds a **signal transformation design environment**: a system where a user describes what they want a guitar signal to *do*, a rule engine maps that intent to circuit blocks using physics, a SPICE simulator validates the result, a real-time DSP engine lets you play through it with your guitar, and a physical layout generator outputs build-ready diagrams.

AI (a local Ollama model) is used **only** at the edges: interpreting natural language intent into structured parameters, and translating simulation results back into plain English. Everything in between is deterministic, rule-based, and auditable.

---

## Goal

Build a local, web-based application called **PedalForge** that allows a user with no coding experience to:

1. Describe a guitar effect in natural language
2. Receive a novel, physics-valid analog circuit design built from components they own
3. Validate that circuit with SPICE simulation
4. Plug in their guitar and play through the circuit in real time via DSP
5. Interact with virtual potentiometers and switches with instant response
6. Iterate conversationally ("more gain," "darker tone," "less fizz")
7. Lock in a "keeper" design
8. Export breadboard and perfboard/stripboard layout diagrams (both sides)
9. Export a bill of materials (BOM) that shows what they have vs. what they need

---

## Hard Constraints

- **No cloud APIs required** — AI runs locally via Ollama (7B parameter model or smaller)
- **Runs locally** — all simulation, DSP, layout generation, and audio processing is local
- **User writes zero code** — all interaction is through the GUI
- **SPICE is authoritative** — the model never overrides physics; if SPICE says it doesn't work, it doesn't work
- **Novel designs are possible** — the system can combine blocks in new ways, not just recall presets
- **Every design is buildable** — outputs map to real, purchasable components
- **Inventory-aware** — the system designs from the user's actual component inventory first
- **Component voltage ratings enforced** — no component is used beyond its rated voltage/current

---

## System Architecture

```
┌─────────────────────────────────┐
│         Chat Interface          │  ← Local Ollama model (intent parsing + explanation only)
└────────────────┬────────────────┘
                 ↓
┌─────────────────────────────────┐
│    Signal Transform Planner     │  ← Rule engine: maps desired sound → transform ops
└────────────────┬────────────────┘
                 ↓
┌─────────────────────────────────┐
│    Circuit Block Compiler       │  ← Deterministic parametric block library
│    + Inventory Constraint       │  ← Designs from user's component stock
└────────────────┬────────────────┘
                 ↓
┌─────────────────────────────────┐
│      SPICE Validation Layer     │  ← ngspice: AC analysis, operating point, bias check
└────────────────┬────────────────┘
                 ↓
┌─────────────────────────────────┐
│     Real-Time DSP Engine        │  ← Circuit model → transfer functions + waveshapers
│  + Audio I/O (sounddevice)      │  ← Guitar in via Focusrite, monitor out
│  + Interactive Knob/Switch GUI  │  ← Virtual pots + switches, instant coefficient update
└────────────────┬────────────────┘
                 ↓
┌─────────────────────────────────┐
│      Physical Output Layer      │
│  Breadboard / Perfboard / Strip │
│  BOM export (have vs. need)     │
└─────────────────────────────────┘
```

---

## Layer 1 — Chat Interface

### Role
The only layer that uses AI. Thin, focused, two jobs only.

### AI Model
- **Runtime:** Ollama, running locally
- **Model:** 7B parameter model or smaller (e.g., Mistral 7B, Llama 3 8B, or a fine-tuned variant)
- **No cloud calls** — everything runs on the user's machine

**Job A — Intent Parsing**
Convert natural language into a `DesignIntent` JSON object:
```json
{
  "transforms": ["soft_clip", "mid_boost"],
  "character": ["warm", "asymmetric"],
  "constraints": {
    "supply_voltage": 9,
    "current_draw_max_ma": 10,
    "input_impedance_kohm": 500,
    "output_impedance_ohm": 100,
    "component_series": "E24"
  },
  "reference_sounds": ["tube screamer", "big muff"],
  "avoid": ["harsh highs", "thin low end"]
}
```

**Job B — Result Explanation**
Convert simulation output numbers into plain English:
- "Your circuit has 18dB of gain with soft clipping. The tone control sweeps from 200Hz to 8kHz. At max gain it draws 4.2mA."

**Job C — Inventory-Aware Recommendations**
When the system designs an alternative due to inventory constraints, the AI explains:
- "I built this with your available components, but if you picked up a pair of 1N34A germanium diodes (~$2), I could make a warmer clipping stage with fewer parts."

### Conversation Memory
Maintain full conversation + design state across turns. User can say "more gain" or "make it darker" and the system understands what circuit to modify.

### Clarification
When intent maps to multiple valid circuit paths, the chat layer asks one clarifying question before proceeding.

---

## Layer 2 — Signal Transform Planner

### Role
Maps desired sound characteristics → ordered list of signal transformation operations.

### Transform Taxonomy
Every guitar pedal effect decomposes into one or more of these primitive transforms:

| Transform | Description | Example Circuits |
|-----------|-------------|-----------------|
| `gain_clean` | Linear amplification | BJT common-emitter, op-amp non-inverting |
| `gain_soft_clip` | Amplify with soft peak limiting | Op-amp + diodes in feedback |
| `gain_hard_clip` | Amplify with hard clipping | Op-amp to rail, comparator |
| `gain_asymmetric` | Different clipping on pos/neg peaks | Mismatched diodes (e.g. LED + germanium) |
| `gain_fuzz` | Heavy saturation, near-square wave | BJT into cutoff/saturation |
| `filter_lp` | Roll off high frequencies | RC low-pass, Sallen-Key |
| `filter_hp` | Roll off low frequencies | RC high-pass |
| `filter_bp` | Boost a frequency band | Gyrator, mid-hump network |
| `filter_notch` | Cut a frequency band | Twin-T, Wien bridge |
| `filter_tonestack` | Interactive bass/mid/treble | Fender/Marshall/Baxandall stack |
| `compress` | Reduce dynamic range | OTA compressor, JFET gain control |
| `modulate_tremolo` | Amplitude modulation | LFO → VCA |
| `modulate_vibrato` | Pitch/phase modulation | LFO → BBD or all-pass chain |
| `modulate_chorus` | Short pitch-modulated delay | LFO → BBD |
| `buffer_input` | High-Z in, low-Z drive | JFET source follower, BJT emitter follower |
| `buffer_output` | Low-Z output drive | Op-amp voltage follower |

### Planning Rules
- Every circuit begins with `buffer_input` and ends with `buffer_output` unless overridden
- Gain stages precede clipping stages
- Tone/filter stages follow clipping stages (standard) or precede (user-specifiable)
- Modulation stages follow tone stages
- Maximum 8 stages in a single pedal

### Output
An ordered `TransformPlan`:
```json
{
  "stages": [
    { "transform": "buffer_input", "params": {} },
    { "transform": "gain_soft_clip", "params": { "gain_db": 20, "clip_type": "symmetric" } },
    { "transform": "filter_tonestack", "params": { "type": "baxandall" } },
    { "transform": "buffer_output", "params": {} }
  ]
}
```

---

## Layer 3 — Circuit Block Compiler

### Role
Maps each `TransformPlan` stage to a concrete, parametric circuit block. Assembles blocks into a complete netlist-ready circuit graph. **All component selections are constrained by the user's inventory.**

### Block Definition Schema
Every block in the library conforms to:
```json
{
  "id": "bjt_common_emitter_v1",
  "transform": "gain_clean",
  "topology": "BJT common-emitter",
  "components": [
    { "id": "Q1", "type": "NPN_BJT", "model": "2N3904", "substitutes": ["BC549C", "BC547"], "max_vce": 40, "max_ic_ma": 200 },
    { "id": "R1", "type": "resistor", "role": "collector_load", "formula": "Vcc / (2 * Ic)", "e_series": "E24", "max_voltage": 50 },
    { "id": "R2", "type": "resistor", "role": "bias_top", "formula": "...", "e_series": "E24" },
    { "id": "R3", "type": "resistor", "role": "bias_bottom", "formula": "...", "e_series": "E24" },
    { "id": "R4", "type": "resistor", "role": "emitter_degeneration", "formula": "R1 / 10", "e_series": "E24" },
    { "id": "C1", "type": "capacitor", "role": "input_coupling", "formula": "1 / (2 * pi * f_low * Rin)", "e_series": "E12", "min_voltage_rating": "2 * Vcc" },
    { "id": "C2", "type": "capacitor", "role": "emitter_bypass", "formula": "...", "e_series": "E12" }
  ],
  "nodes": ["in", "out", "vcc", "gnd"],
  "parameters": {
    "gain_db": { "min": 6, "max": 40, "default": 20 },
    "f_low_hz": { "min": 20, "max": 500, "default": 80 },
    "supply_voltage": { "min": 5, "max": 18, "default": 9 }
  },
  "spice_template": "...",
  "dsp_model": {
    "type": "transfer_function",
    "description": "First-order highpass (coupling) → gain stage → first-order lowpass (bandwidth limit)",
    "nonlinear_elements": []
  },
  "behavioral_description": "Single BJT common-emitter amplifier. Warm, slightly colored gain. Gain set by collector/emitter resistor ratio.",
  "valid_ranges_notes": "Gain above 35dB may require careful bypassing. Ic should be 0.5–2mA for low noise."
}
```

### Inventory Integration
The compiler resolves components in this order:
1. **Exact match** — user has the calculated E-series value in stock
2. **Nearest available** — user has a close value; compiler checks if substitution keeps the circuit within spec (recalculates dependent values, re-validates operating point)
3. **Substitute component** — different part that fills the same role (e.g., BC549C instead of 2N3904)
4. **Unavailable** — component is not in inventory; flagged in BOM as "need to buy" with a recommendation explaining what it unlocks

If a design cannot be built from inventory at all, the system:
- **Still generates the design** as a reference
- **Proposes an alternative** using available components, explaining trade-offs
- **Lists the minimum purchase** needed to build the original design

### Voltage Rating Enforcement
- Every component in the compiled circuit is checked against its voltage/current rating
- Capacitor voltage rating must be ≥ 2× the DC voltage across it (standard derating)
- Transistor Vce must be within absolute maximum rating
- Op-amp supply voltage must be within rated range
- If a violation is detected, the compiler substitutes a higher-rated component or flags an error

### Core Block Library (implement all of these)

**Buffers**
- JFET source follower (input buffer)
- BJT emitter follower (input/output buffer)
- Op-amp voltage follower (output buffer)

**Gain Stages**
- BJT common-emitter (clean gain)
- JFET common-source (clean, colored gain)
- Op-amp non-inverting (clean, precise gain)
- Op-amp inverting (clean, precise gain)

**Clipping Stages**
- Op-amp + symmetric silicon diodes (soft clip)
- Op-amp + symmetric LED clipping (soft clip, higher threshold)
- Op-amp + germanium diodes (soft clip, warm)
- Op-amp + asymmetric diode pairs (asymmetric clip)
- Op-amp hard clip (to rail)
- BJT fuzz stage (heavy saturation)
- Germanium fuzz (two-stage BJT, vintage)

**Filter / Tone**
- First-order RC low-pass (fixed)
- First-order RC high-pass (fixed)
- Second-order Sallen-Key low-pass
- Gyrator mid-boost
- Presence control (high-shelf)
- Baxandall tone stack (bass + treble)
- Fender-style tone stack (bass + mid + treble)
- Marshall-style tone stack

**Compression**
- OTA-based compressor (CA3080 / LM13700)
- JFET gain cell

**Modulation**
- Triangle/sine LFO (op-amp)
- Tremolo (LFO → JFET VCA)

### Assembly Rules
- Nodes are connected by matching output node of stage N to input node of stage N+1
- Power nodes (VCC, GND) are global
- Coupling capacitors are auto-inserted between stages unless both stages are DC-coupled
- Component IDs are namespaced per stage (e.g., `S1_R1`, `S2_Q1`)
- Every design exposes exactly four terminals: **GND, 9V, IN, OUT** (compatible with the user's magnetic modular pedal system)

### Parameter Calculation Engine
All component values are **calculated from formulas**, not looked up from a table:
- Resistor values calculated from gain targets, bias points, impedance requirements
- Capacitor values calculated from cutoff frequency targets
- All values rounded to nearest E12/E24 series value after calculation, **then snapped to nearest value available in inventory** (with re-validation)
- Operating point verified: Vcc/3 < Vbias < 2*Vcc/3 for all active stages
- The system implicitly minimizes component count — fewer parts is always preferred when multiple topologies achieve the same result

---

## Layer 4 — SPICE Validation Layer

### Role
Validates the assembled circuit using ngspice. **SPICE is used for validation only, not for audio processing.** Real-time audio is handled by the DSP engine (Layer 5).

### Requirements
- Output standard SPICE2/ngspice syntax
- Include `.model` definitions for all semiconductors used
- Include `.ac` analysis directives for frequency response validation

### Analyses Run Automatically
- `.op` — DC operating point (bias check: are all transistors in their expected region?)
- `.ac dec 100 20 20000` — frequency response (20Hz–20kHz, magnitude + phase)
- DC current draw measurement

### Outputs Extracted
- Frequency response curve (magnitude + phase)
- Gain at 1kHz
- -3dB points (low and high)
- Clipping threshold voltage
- DC current draw
- THD estimate at 1kHz (via small-signal analysis)

### Validation Checks
After simulation, the system automatically verifies:
- All transistors are biased in their expected operating region
- No component exceeds its voltage/current rating under signal conditions
- Frequency response matches the intended transform (e.g., a low-pass filter actually rolls off highs)
- Current draw is within the supply constraint

### Non-Convergence Handling
If ngspice simulation fails to converge (common with fuzz/heavy clipping circuits):

1. **Tier 1 — Auto-retry with relaxed tolerances:** Increase RELTOL, enable GMIN stepping. This silently resolves ~70% of convergence failures.
2. **Tier 2 — Alternate integration method:** Switch from trapezoidal to Gear method. Resolves another ~15%.
3. **Tier 3 — Diagnose and report:** Analyze the failure to identify the likely cause (gain too high, bias point at rail, impossible operating point). Report to the user in plain English via the chat interface: *"The gain stage is trying to operate outside its linear range. Try reducing gain below 35dB or I can adjust the bias network."*
4. **Never silently fail.** Always show what was attempted and what went wrong.

### Pot / Switch Handling in Validation
Potentiometers are represented as two resistors (R_top + R_bottom) with a parameter `wiper_position` (0.0–1.0). For validation, the system runs AC analysis at three pot positions (0.0, 0.5, 1.0) to verify behavior across the sweep range.

---

## Layer 5 — Real-Time DSP Engine + Interactive GUI

### DSP Architecture
The real-time audio engine converts the validated circuit model into a DSP processing chain:

**Linear stages** (filters, clean gain, buffers):
- Extract transfer function coefficients from the circuit equations
- Implement as IIR biquad filters or state-variable filters
- Coefficients recalculated instantly when a knob moves

**Nonlinear stages** (clipping, fuzz, compression):
- Diode clipping → waveshaping function (tanh approximation, piecewise polynomial, or lookup table derived from the diode equation with actual component parameters)
- BJT saturation → Ebers-Moll model simplified to a static nonlinearity + filtering
- JFET compression → variable-gain element driven by envelope follower

**Modulation stages** (tremolo, vibrato, chorus):
- LFO generates control signal
- Applied to gain (tremolo) or delay time (chorus/vibrato) in the DSP chain

Each block in the circuit library includes a `dsp_model` field that defines how to convert its SPICE-validated parameters into real-time DSP coefficients.

### Audio I/O
- **Backend:** Python `sounddevice` library for audio device management
- **Target interface:** Focusrite Scarlett Solo (USB-C)
- **Input:** Guitar signal from audio interface input
- **Output:** Processed signal to audio interface output (headphones/monitors)
- **Sample rate:** 44.1kHz or 48kHz (match device default)
- **Buffer size:** 128–256 samples (~3–6ms latency at 48kHz)
- **Audio device selection** exposed in GUI — user picks input and output device from dropdown

### Audio Flow
```
Guitar → Audio Interface → sounddevice input callback
    → DSP chain (per-sample or per-block processing)
    → sounddevice output callback → Audio Interface → Monitors/Headphones
```

### Bypass
- **On/off toggle** in the GUI — when off, input passes directly to output (true bypass in DSP)
- No physical bypass circuit needed — the user's magnetic modular system handles physical bypass

### Interactive GUI
**Tech stack:** React frontend + FastAPI backend. Python handles all audio and simulation. React handles all UI.

**GUI elements:**
- **Audio device panel:** Input/output device dropdowns, buffer size selector, audio engine start/stop
- **Bypass toggle:** Large, obvious on/off switch for the effect
- **Waveform display:** Real-time time-domain waveform of the output signal
- **Spectrum display:** Real-time frequency spectrum (FFT) of the output signal
- **Frequency response overlay:** SPICE-validated AC response curve shown alongside real-time spectrum
- **Virtual knobs** for every potentiometer in the circuit (SVG rotary knobs, click-drag to turn)
- **Virtual switches** for every switch in the circuit
- **Chat panel:** Conversation with the AI for design iteration
- **Keeper button:** Saves current parameter state + circuit to design history

**Aesthetic direction:** Clean dark theme. Functional, not flashy. Dark background, clear contrast, readable labels. Hardware aesthetic polish (CRT glow, scanline textures, phosphor traces) deferred to a later phase.

---

## Layer 6 — Physical Output Layer

### Terminal Convention
Every design outputs a circuit with exactly four labeled connection points:
- **GND** — ground reference
- **9V** — power supply positive
- **IN** — signal input
- **OUT** — signal output

These map directly to the user's magnetic modular pedal system. No bypass switching, no jacks, no enclosure considerations.

### Schematic
- Export circuit as SVG schematic using standard electronic symbols
- Auto-route using basic force-directed or hierarchical layout
- Terminal points (GND, 9V, IN, OUT) clearly labeled at circuit boundaries

### Breadboard Diagram
- Map all components to breadboard positions
- Output as SVG with color-coded jumper wires
- Show power rails clearly
- Terminal connection points clearly marked

### Perfboard Layout
- Grid-based placement (0.1" pitch)
- Optimize for short trace lengths and minimal crossings
- Output both sides: component side (top) and solder side (bottom)
- Solder side is mirrored, traces shown as lines between pad dots
- Export as SVG (printable at 1:1 scale)

### Stripboard Layout
- Same as perfboard but constrain traces to horizontal copper strips
- Mark strip cuts clearly
- Output both sides

### BOM Export
- CSV format
- Columns: Reference, Type, Value, Tolerance, Package, **In Stock** (quantity available), **Need** (quantity required minus stock), Suggested Part Number
- Grouped by: "Have" (can build now) and "Need to Buy"
- The AI provides a plain-English summary: what the user can build today vs. what a small purchase would unlock

---

## Component Inventory System

### Overview
PedalForge maintains a persistent inventory of the user's actual electronic components. The circuit compiler designs from this inventory first, and clearly communicates what's missing.

### Data Model
```json
{
  "id": "uuid",
  "type": "resistor",
  "value": 10000,
  "unit": "ohm",
  "tolerance": "5%",
  "package": "through-hole",
  "voltage_rating": 50,
  "quantity": 25,
  "notes": "1/4W carbon film"
}
```

Component types: resistor, capacitor, diode, LED, NPN_BJT, PNP_BJT, N_JFET, P_JFET, op_amp, potentiometer, switch

### Inventory GUI
- **Add component:** Form with type, value, quantity, package, voltage rating, notes
- **Browse/search:** Filter by type, value range, or keyword
- **Edit quantity:** Quick increment/decrement (built 2 pedals? subtract the parts used)
- **Bulk operations:** Select multiple and delete, or adjust quantities
- **Low stock warnings:** Highlight components with quantity ≤ 2

### Storage
- Persisted in SQLite database alongside design history
- Survives app restarts

### Compiler Integration
When the compiler selects component values:
1. Calculate ideal E-series value from circuit formulas
2. Check inventory for exact match → use it
3. Check inventory for nearest available value → recalculate circuit, verify still within spec
4. Check inventory for substitute parts → verify compatibility
5. If no inventory match: flag as "need to buy" and **also generate an alternative design** using only available parts, with the AI explaining the trade-off

### Purchase Recommendations
The AI analyzes the user's inventory gaps and suggests strategic purchases:
- "You have lots of silicon diodes but no germanium. Picking up a 10-pack of 1N34A (~$3) would unlock warm vintage clipping in your designs."
- "A TL072 dual op-amp ($0.50) would let me build Baxandall tone stacks, which your current inventory can't support."

---

## Iteration Loop

The core user experience:

```
1. User: "I want something like a Rat but warmer and with a usable tone control"
2. System: Parses intent → TransformPlan → Circuit (from inventory) → SPICE validates → DSP model ready
3. GUI: Shows frequency response, knobs for gain + tone pots, bypass toggle
4. User: Clicks bypass ON, plays guitar through the effect in real time
5. User: Twists gain knob to 3/4 — DSP coefficients update instantly, sound changes live
6. User: "It's too harsh in the mids"
7. System: Identifies mid content → adjusts tone stack parametrics → re-validates with SPICE → updates DSP
8. User: Presses Keeper
9. System: Saves design snapshot
10. User: Requests breadboard layout
11. System: Generates and displays layout SVG with BOM (shows 2 components need purchasing)
```

---

## Keeper / Design History

Each "keeper" saves:
```json
{
  "id": "uuid",
  "timestamp": "...",
  "name": "Warm Rat v3",
  "intent_description": "RAT-style with warmer mids and usable tone control",
  "transform_plan": { ... },
  "circuit_graph": { ... },
  "spice_netlist": "...",
  "parameter_state": { "S2_pot1_wiper": 0.72, "S3_pot1_wiper": 0.45 },
  "simulation_results": {
    "gain_1khz_db": 24.3,
    "f_low_3db_hz": 85,
    "f_high_3db_hz": 7200,
    "current_draw_ma": 4.1
  },
  "inventory_snapshot": {
    "all_in_stock": false,
    "missing_components": ["1N34A germanium diode x2"]
  },
  "dsp_model_state": { ... }
}
```

Design history is browsable in the GUI. User can reload any keeper, plug in their guitar, and play through it again.

---

## Constraints System

User-specifiable per design, enforced by the compiler:

| Constraint | Default | Enforced By |
|------------|---------|-------------|
| Supply voltage | 9V | Bias calculations, component voltage ratings |
| Max current draw | 10mA | Operating point checker |
| Input impedance | ≥500kΩ | Input buffer selection |
| Output impedance | ≤1kΩ | Output buffer selection |
| Component series | E24 | Value rounding (then inventory snap) |
| Opamp family | TL07x | Model substitution list |
| Component voltage ratings | Per datasheet | Compiler enforces derating (2× for caps) |

---

## Phase Plan

### Phase 1 — Core Engine
- [ ] Component + block library (all blocks listed above, fully parametric, with DSP model definitions)
- [ ] Parameter calculation engine (formulas, E-series rounding)
- [ ] Transform planner (rule engine, taxonomy above)
- [ ] Circuit assembler (node connection, coupling cap insertion)
- [ ] SPICE netlist generator
- [ ] ngspice integration (subprocess, output parsing, non-convergence recovery)
- [ ] Component inventory system (SQLite, CRUD GUI)
- [ ] Inventory-aware component selection in compiler
- [ ] Basic web GUI (React frontend, frequency response display)
- [ ] Ollama integration for intent parsing

### Phase 2 — Real-Time Audio + Interaction
- [ ] DSP engine: transfer function extraction from circuit model
- [ ] DSP engine: nonlinear waveshaping for clipping/fuzz stages
- [ ] Audio device selection (input/output) via sounddevice
- [ ] Real-time audio processing pipeline (guitar in → DSP → monitors out)
- [ ] Bypass toggle
- [ ] Virtual knobs + switches with instant DSP coefficient update
- [ ] Real-time waveform and spectrum display
- [ ] Keeper system + design history

### Phase 3 — Physical Output
- [ ] SVG schematic export (4-terminal: GND, 9V, IN, OUT)
- [ ] Breadboard layout generator
- [ ] Perfboard layout generator (both sides)
- [ ] Stripboard layout generator
- [ ] BOM CSV export (have vs. need columns)
- [ ] AI-generated purchase recommendations

### Phase 4 — Polish + Extensions
- [ ] CRT/oscilloscope aesthetic (scanline shaders, phosphor glow, Davies 1900h knob SVGs)
- [ ] Design history browser in GUI
- [ ] Expanded block library (BBD chorus, spring reverb approximation, etc.)
- [ ] Inventory import/export (CSV)
- [ ] VST2/3 export (circuit model → DSP approximation via JUCE/DPF)

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+ |
| Web framework | FastAPI (local server) |
| Frontend | React |
| Simulation | ngspice (installed locally, called via subprocess) |
| Real-time DSP | Python: numpy + scipy.signal for filter coefficients, sounddevice for audio I/O |
| AI layer | Ollama (local, 7B model — e.g., Mistral 7B, Llama 3 8B) |
| Data storage | SQLite (design history + component inventory) |
| Block library | JSON files in repo (version-controlled) |
| Layout generation | Custom SVG renderer (no external dep required) |
| Packaging | Single `./start.sh` or `start.bat` entry point |

---

## Setup Requirements

The system must:
- Install with a single script (`setup.sh` / `setup.bat`)
- Start with a single command (`./start.sh` / `start.bat`)
- Open the GUI automatically in the default browser
- Require only: Python 3.11+, ngspice, Ollama (with a pulled model), and an audio interface
- Work on Windows (primary — user runs Windows 11), macOS and Linux as secondary targets

---

## AI Usage Policy (Important)

The local Ollama model is called **only** for:
1. Parsing user's natural language into `DesignIntent` JSON
2. Translating simulation results into plain English explanation
3. Asking clarifying questions when intent is ambiguous
4. Generating inventory-aware purchase recommendations

The AI model is **never** called for:
- Component value calculation (that's the formula engine)
- Circuit topology selection (that's the rule engine)
- Simulation (that's ngspice)
- DSP processing (that's the DSP engine)
- Layout generation (that's the layout engine)

The AI's output is always validated against the schema before use. If the output doesn't parse, the system asks the user to rephrase rather than retrying blindly.

The system prompt for the Ollama model must:
- Define the `DesignIntent` JSON schema explicitly
- List all valid transform names
- Instruct the model to output only valid JSON for intent parsing calls
- Prevent the model from inventing component values or circuit topologies
- Be optimized for small model reliability (clear examples, constrained output format)

---

## Success Criteria

The system is working when it can:

1. Accept "I want a fuzz pedal, warm and gated" and produce a validated circuit from the user's inventory
2. Let the user plug in their guitar and play through the effect in real time
3. Let the user twist a knob and hear the change instantly
4. Produce a buildable breadboard layout for that circuit
5. Export a BOM showing what they have and what they need to buy
6. Accept "make it less gated" and produce a meaningfully different result
7. Recommend a $5 purchase that would unlock a whole new category of sounds

---

## What This Is Not

- Not a general-purpose circuit simulator (scope is guitar pedal signal chain only)
- Not a PCB layout tool (perfboard/stripboard only, no PCB autorouter)
- Not a DAW or plugin host (it's a design tool with real-time preview, not a recording environment)
- Not a cloud service (everything runs locally, no external API calls)
- Not a parts store (it works with what you have and tells you what to get)
