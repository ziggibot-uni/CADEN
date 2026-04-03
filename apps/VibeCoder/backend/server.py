"""WebSocket server for VibeCoder GUI mode.

Exposes the agent as a WebSocket endpoint so the CADEN frontend
can send messages and receive streaming responses.

Protocol — Client sends:
  {"type": "message", "content": "user input"}
  {"type": "command", "command": "/clear"}
  {"type": "set_workspace", "path": "C:\\path\\to\\project"}
  {"type": "confirm_response", "approved": true|false}

Protocol — Server sends:
  {"type": "status", "content": "thinking..."}
  {"type": "plan", "content": "1. Read file\\n2. ..."}
  {"type": "tool_call", "name": "read_file", "args": {...}}
  {"type": "tool_result", "name": "read_file", "status": "ok|err", "preview": "..."}
  {"type": "confirm", "tool": "edit_file", "args": {...}}
  {"type": "done", "content": "full response"}
  {"type": "advisory", "kind": "review|impact|docs|import_error", "items": [...]}
  {"type": "stats", "episodes": N, "lessons": N, "model": "...", "workspace": "..."}
  {"type": "error", "content": "error message"}
"""

import asyncio
import json
import os
import re
import sys
import threading
from typing import Optional

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False


class ServerConsole:
    """Console substitute for server mode.

    Sends structured messages to the WebSocket client via asyncio Queue.
    Supports confirmation callbacks that block the agent thread until the
    WebSocket client responds.
    """

    def __init__(self, loop, outbound):
        self._loop = loop
        self._outbound = outbound
        self._confirm_event = threading.Event()
        self._confirm_approved = False

    def _send(self, msg):
        self._loop.call_soon_threadsafe(self._outbound.put_nowait, msg)

    # ── Rich-compatible print ──────────────────────────────────────────────
    def print(self, *args, **kwargs):
        text = " ".join(str(a) for a in args)
        # Strip Rich markup tags
        text = re.sub(r'\[/?[^\]]*\]', '', text)
        text = text.strip()
        if text and text not in ('...', ''):
            self._send({"type": "status", "content": text})

    # ── Structured hooks (called by agent.py) ──────────────────────────────
    def on_tool_call(self, name, args):
        self._send({
            "type": "tool_call",
            "name": name,
            "args": {k: str(v)[:300] for k, v in args.items()},
        })

    def on_tool_result(self, name, result, status):
        self._send({
            "type": "tool_result",
            "name": name,
            "status": status,
            "preview": result[:500],
        })

    def on_plan(self, plan_text):
        self._send({"type": "plan", "content": plan_text})

    def on_advisory(self, kind, items):
        self._send({"type": "advisory", "kind": kind, "items": items[:10]})

    # ── Confirmation callbacks (block agent thread) ────────────────────────
    def confirm_edit(self, tool_args):
        self._confirm_event.clear()
        self._confirm_approved = False
        self._send({
            "type": "confirm",
            "tool": "edit",
            "args": {k: str(v)[:800] for k, v in tool_args.items()},
        })
        self._confirm_event.wait(timeout=300)  # 5 min timeout
        return self._confirm_approved

    def confirm_run(self, tool_args):
        self._confirm_event.clear()
        self._confirm_approved = False
        self._send({
            "type": "confirm",
            "tool": "run",
            "args": {k: str(v)[:500] for k, v in tool_args.items()},
        })
        self._confirm_event.wait(timeout=300)
        return self._confirm_approved

    def handle_confirm_response(self, approved):
        self._confirm_approved = approved
        self._confirm_event.set()


def _inject_caden_context(workspace_path: str):
    """If the workspace is inside the CADEN apps directory, build the plugin
    development context dynamically from real source files so it never drifts.
    """
    try:
        from agent import working_memory

        normalized = os.path.normpath(workspace_path).lower()
        is_caden_build = (
            os.path.join("caden", "apps") in normalized
            or normalized.endswith(os.path.join("caden", "caden"))
        )
        if not is_caden_build:
            return

        # Locate CADEN root (the dir that contains caden-colors.js and apps/)
        caden_root = os.path.normpath(workspace_path)
        for _ in range(5):
            if os.path.isfile(os.path.join(caden_root, "caden-colors.js")):
                break
            parent = os.path.dirname(caden_root)
            if parent == caden_root:
                return
            caden_root = parent
        else:
            return

        parts = ["# CADEN Plugin Development Reference (auto-generated)\n"]

        # ── 1. Existing plugin ports ──────────────────────────────────────
        apps_dir = os.path.join(caden_root, "apps")
        taken_ports = {}
        next_port = 5181
        if os.path.isdir(apps_dir):
            import json as _json
            for name in sorted(os.listdir(apps_dir)):
                pj = os.path.join(apps_dir, name, "caden-plugin.json")
                if os.path.isfile(pj):
                    try:
                        with open(pj, "r", encoding="utf-8") as f:
                            cfg = _json.load(f)
                        taken_ports[name] = cfg.get("port", "?")
                    except Exception:
                        pass
            parts.append("## Taken ports")
            for app_name, port in taken_ports.items():
                parts.append(f"- {app_name}: {port}")
            next_port = max((p for p in taken_ports.values() if isinstance(p, int)), default=5179) + 1
            parts.append(f"- **Next available port: {next_port}**\n")

        # ── 2. caden-plugin.json format (from a real example) ─────────────
        parts.append("## caden-plugin.json format")
        parts.append("Every CADEN plugin folder MUST have this file at its root.\n")
        parts.append("### Dev-Server plugin (hot reload)")
        parts.append('```json\n{"name":"MyApp","install_command":"npm install","dev_command":"npm run dev","port":' + str(next_port) + '}\n```')
        parts.append("### Static plugin (pre-built)")
        parts.append('```json\n{"name":"MyApp","entry":"dist/index.html"}\n```\n')

        # ── CRITICAL: common failure modes ────────────────────────────────
        parts.append("## CRITICAL: Common failure — \"localhost refused to connect\"")
        parts.append(
            "This error means the dev server never started. It happens when `caden-plugin.json` "
            "declares a `dev_command` but the required project files are missing.\n"
        )
        parts.append(
            "**Rule: if you write a `dev_command` in caden-plugin.json, you MUST also create "
            "ALL of these files in the same folder or the plugin will never load:**\n"
            "- `package.json` (with a `dev` script that runs Vite on the declared port)\n"
            "- `vite.config.js` (with `server: { port: PORT }` matching caden-plugin.json)\n"
            "- `index.html` (Vite entry point)\n"
            "- `src/main.jsx` (React entry)\n"
            "- `src/App.jsx`\n"
            "- `src/index.css`\n"
            "- `tailwind.config.js`\n"
            "- `postcss.config.js`\n\n"
            "**A plain `.html` file, a `.py` backend script, or a `.sql` schema file are NOT a dev server. "
            "They cannot listen on a port. CADEN will call `npm run dev` and fail silently.\n\n"
            "If your app has a Python backend, you still need the full Vite/React frontend "
            "scaffold above; the Python process is a separate backend the frontend calls via fetch/WebSocket. "
            "Never rely on Python alone to serve the plugin UI.\n\n"
            "If the app is purely static (no hot reload needed), use the `entry` form instead "
            "and point it at a real built `dist/index.html`.**\n"
        )

        # ── 3. Color variables (read from caden-colors.js) ────────────────
        colors_file = os.path.join(caden_root, "caden-colors.js")
        if os.path.isfile(colors_file):
            with open(colors_file, "r", encoding="utf-8") as f:
                colors_src = f.read()
            # Extract the cadenColorDefaults object lines
            in_defaults = False
            color_lines = []
            for line in colors_src.splitlines():
                if "cadenColorDefaults" in line and "{" in line:
                    in_defaults = True
                    continue
                if in_defaults:
                    if "};" in line:
                        break
                    stripped = line.strip().rstrip(",")
                    if stripped and ":" in stripped:
                        color_lines.append(stripped)
            if color_lines:
                parts.append("## CADEN CSS variables (from caden-colors.js)")
                parts.append("These are set on :root as `R G B` strings.")
                parts.append("Use `rgb(var(--c-accent))` in CSS, or Tailwind classes like `bg-surface`, `text-accent`.\n")
                parts.append("| Variable | Default |")
                parts.append("|----------|---------|")
                for cl in color_lines:
                    var_name, hex_val = [s.strip().strip('"') for s in cl.split(":", 1)]
                    parts.append(f"| `{var_name}` | `{hex_val.strip()}` |")
                parts.append("")

        # ── 4. Theme postMessage handler (from colorOverrideScript.ts) ────
        parts.append("## Required: postMessage theme listener")
        parts.append("CADEN sends theme data to plugins via postMessage.")
        parts.append("Add this in your root component's useEffect:\n")
        parts.append("```jsx")
        parts.append("useEffect(() => {")
        parts.append("  const handler = (e) => {")
        parts.append('    if (e.data?.type === "caden-font-scale")')
        parts.append('      document.documentElement.style.setProperty("--font-scale", String(e.data.scale));')
        parts.append('    if (e.data?.type === "caden-contrast")')
        parts.append('      document.documentElement.style.setProperty("--contrast", String(e.data.contrast));')
        parts.append('    if (e.data?.type === "caden-theme-colors" && e.data.colors)')
        parts.append("      for (const [key, val] of Object.entries(e.data.colors))")
        parts.append("        document.documentElement.style.setProperty(key, val);")
        parts.append("  };")
        parts.append('  window.addEventListener("message", handler);')
        parts.append('  return () => window.removeEventListener("message", handler);')
        parts.append("}, []);\n```\n")

        # ── 5. Real boilerplate (from PedalManifest as reference) ─────────
        ref_app = os.path.join(apps_dir, "PedalManifest") if os.path.isdir(apps_dir) else None
        if ref_app and os.path.isdir(ref_app):
            for fname, label in [
                ("tailwind.config.js", "tailwind.config.js"),
                ("postcss.config.js", "postcss.config.js"),
                ("vite.config.js", "vite.config.js (first 12 lines)"),
                ("package.json", "package.json"),
            ]:
                fpath = os.path.join(ref_app, fname)
                if os.path.isfile(fpath):
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()
                    if "first 12" in label:
                        content = "\n".join(content.splitlines()[:12])
                    parts.append(f"## Reference: {label} (from PedalManifest)")
                    ext = fname.rsplit(".", 1)[-1]
                    parts.append(f"```{ext}\n{content.strip()}\n```\n")

        # ── 6. File structure ─────────────────────────────────────────────
        parts.append("## Minimal file structure")
        parts.append("```")
        parts.append("my-app/")
        parts.append("  caden-plugin.json     ← REQUIRED")
        parts.append("  package.json")
        parts.append("  vite.config.js        ← port must match caden-plugin.json")
        parts.append("  tailwind.config.js    ← import cadenColors from ../../caden-colors.js")
        parts.append("  postcss.config.js")
        parts.append("  index.html")
        parts.append("  src/")
        parts.append("    main.jsx")
        parts.append("    App.jsx             ← postMessage theme listener")
        parts.append("    index.css           ← @tailwind directives + :root vars")
        parts.append("```\n")

        parts.append("## Registration")
        parts.append("After building, use the 'Register' button in AppBuilder or CADEN's plugin manager to add the app as a tab.")

        working_memory["caden_plugin_context"] = "\n".join(parts)
    except Exception:
        pass  # Never crash the server over context injection


def start_server(port: int = 5180, workspace: Optional[str] = None):
    if not HAS_WEBSOCKETS:
        print("Error: websockets package not installed. Run: pip install websockets")
        sys.exit(1)

    from tools import set_workspace, get_workspace
    from model import get_active_model

    ws = workspace or os.getcwd()
    set_workspace(ws)

    print(f"VibeCoder server starting on ws://localhost:{port}")
    print(f"  Model: {get_active_model()}")
    print(f"  Workspace: {get_workspace()}")

    async def handle_client(websocket):
        from agent import agent_converse, working_memory
        from memory import episode_count
        from caden_bridge import lesson_count

        loop = asyncio.get_event_loop()
        outbound = asyncio.Queue()
        console = ServerConsole(loop, outbound)

        # ── Drain outbound queue → WebSocket ──────────────────────────────
        async def drain():
            try:
                while True:
                    msg = await outbound.get()
                    if msg is None:
                        break
                    await websocket.send(json.dumps(msg))
            except Exception:
                pass

        drain_task = asyncio.create_task(drain())

        # ── Helper to build & send stats ──────────────────────────────────
        async def send_stats():
            await websocket.send(json.dumps({
                "type": "stats",
                "episodes": episode_count(),
                "lessons": lesson_count(),
                "model": get_active_model(),
                "workspace": get_workspace(),
            }))

        await send_stats()

        # ── Agent runner (starts as asyncio task so receive keeps going) ──
        agent_task = None

        async def run_agent(content):
            try:
                result = await loop.run_in_executor(
                    None, agent_converse, content, console
                )
                await websocket.send(json.dumps({
                    "type": "done", "content": result or "(no response)"
                }))
            except Exception as e:
                await websocket.send(json.dumps({
                    "type": "error", "content": str(e)
                }))
            await send_stats()

        # ── Receive loop ──────────────────────────────────────────────────
        try:
            async for raw_msg in websocket:
                try:
                    msg = json.loads(raw_msg)
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({
                        "type": "error", "content": "Invalid JSON"
                    }))
                    continue

                msg_type = msg.get("type", "message")

                # ── Confirm response (unblocks agent thread) ──────────────
                if msg_type == "confirm_response":
                    console.handle_confirm_response(msg.get("approved", False))
                    continue

                # ── Workspace switch ──────────────────────────────────────
                if msg_type == "set_workspace":
                    path = msg.get("path", "")
                    if path and os.path.isdir(path):
                        set_workspace(path)
                        os.chdir(path)
                        # Inject CADEN plugin context into working memory
                        # so the agent knows how to build CADEN-compatible apps.
                        _inject_caden_context(path)
                        await websocket.send(json.dumps({
                            "type": "status",
                            "content": f"Workspace set to: {path}"
                        }))
                        await send_stats()
                    else:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "content": f"Invalid path: {path}"
                        }))
                    continue

                # ── Slash commands ────────────────────────────────────────
                if msg_type == "command":
                    cmd = msg.get("command", "")
                    if cmd == "/clear":
                        working_memory["chat_history"].clear()
                        working_memory["files_in_scope"].clear()
                        working_memory["current_task"] = None
                        working_memory["current_plan"] = None
                        working_memory["caden_plugin_context"] = None
                        await websocket.send(json.dumps({
                            "type": "status", "content": "Context cleared."
                        }))
                    continue

                # ── User message ──────────────────────────────────────────
                if msg_type == "message":
                    content = msg.get("content", "").strip()
                    if not content:
                        continue

                    # ── Background: log to CADEN's chat_log + mood + session ──
                    def _bg_caden_log(text):
                        from caden_bridge import (
                            log_chat_to_caden,
                            extract_and_store_mood,
                            record_appbuilder_session,
                        )
                        log_chat_to_caden(text)
                        extract_and_store_mood(text)
                        record_appbuilder_session(len(text))
                    threading.Thread(
                        target=_bg_caden_log, args=(content,), daemon=True
                    ).start()

                    # Cancel previous agent if still running
                    if agent_task and not agent_task.done():
                        agent_task.cancel()

                    agent_task = asyncio.create_task(run_agent(content))

        finally:
            # Clean shutdown
            if agent_task and not agent_task.done():
                agent_task.cancel()
            await outbound.put(None)  # sentinel to stop drain
            drain_task.cancel()

    async def serve():
        async with websockets.serve(handle_client, "localhost", port):  # type: ignore[possibly-undefined]
            print(f"  Listening on ws://localhost:{port}")
            await asyncio.Future()  # run forever

    asyncio.run(serve())
