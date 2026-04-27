This is immutable. Github Copilot and Claude are prohibited from changing this file in any way.
# CADEN: Chaos-Aiming and Distress-Evasion Navigator
- Life assistant to Sean Kellogg
- also could be thought of as an executive function prosthesis
- Sean has ADHD, autism, bipolar, and severe synesthesia. CADEN is not bespoke to these conditions, but learns what works for Sean through deterministic statistics math.
- Tracks Sean's behavior over time and learns how to predict Sean even as he changes and enters new phases of life. Sean is going to change, and CADEN counts on it
- Sean is a chaos-cannon. CADEN aims the chaos. Sean is brilliant but unfocused. CADEN bridges the gap. Together they are a very productive and high-functioning team.

## CADEN's Job Summarized
- Track:
  - Mood
  - Energy
  - Productivity
- Balance all three: maximize each parameter without tanking the other two.
## Cloud LLMs Are Out of the Question
Cloud models:
- are expensive as fuck
- are ran by corrupt companies
- are breaches of privacy

## Hardware:
- RTX 3060, 12 GB VRAM
- AMD Ryzen 7 2700X Eight-Core Processor on an x86_64 system

## The Problems With an All-Local-LLM CADEN
- they don't remember
- frozen in time
- can't learn online
- no room for growth without manual implementation/continued fine-tuning
- hallucinate
- context bloat
- slow if overused (expensive)

### On the other hand...
- good at reasoning
- good at abstract thinking

## The Problem With an All-Deterministic CADEN
- poor reasoning and abstract thinking
- only can do exactly as it is told and nothing else
- parsers reach their limits quickly (there will ALWAYS be another edge-case)
- trying to account for every possibility is a trap. This requires an unjustified amount of maintenance

### On the other hand...
- very cheap computation
- reliable
- better than LLMs for concrete computation

## So a Union Then?
Yes, exactly!
- LLM is used for reasoning
- Deterministic framework guides and guards the LLM

## Architecture
- documentation and reliability first
- no hand-written heuristics: all behavior is learned (yes it will suck for a while, but it beats having hand-written crap polluting it's mind from the beginning). the moment a bespoke heuristic is written, caden collapses under pollution. let him figure things outs for himself, and if he can't, you can improve the mechanisms themselves but don't add rules to satisfy shortcomings in the present or you will fall into the "just one more rule" trap. not even one rule.
- operational presentation/retrieval policies are allowed when they are generic and not claims about Sean himself. current committed examples: the dashboard day rolls over at 5 AM local time to better match circadian rhythm than strict midnight, and Libbie penalizes overly long memories during retrieval so concise memories are favored and LLM context bloat stays under control.
- Modular
- Simple
- Python-only for everything, even if it means a slightly uglier GUI compared to JS or Rust
- NO FALLBACKS! This is not a corporate product: only Sean will be using CADEN.
  - If something fails, it needs to fail loudly with no fallback. Otherwise the codebase becomes a pile of junk code with useful pieces mixed in and that is a NIGHTMARE so avoid that at all costs!
- ollama used for the LLM (model is chosen in CADEN's settings)
  - will be a 7b-10b model, which means that the LLM is only the membrane and reasoning, but it will be relying very heavily on the framework for memory and past lessons learned.
  - model's scope stays small, but many calls can be made. be careful not to fragment too much or you'll lose the plot.

### Core GUI Architecture (Textual Apps)
- The entire CADEN graphical interface is a unified `TabbedContent` container driven by Textual. 
- Everything Sean interacts with is an App built as a `TabPane`.
- The current implementation of CADEN's GUI (`caden/ui/app.py`) is the root container, and the v0 "App" logic acts as the default **Dashboard** tab.
- All subsequent apps (Sprocket, Thought Dump, Project Manager) will use the exact same tab registration layout. They are all sibling tabs.

### Dashboard (3 panels) (TBC)
- The first/default `TabPane` in CADEN's GUI.
- To the left, the "today" panel which shows everything that Sean has in his google calendar and google tasks for the current circadian day, PLUS whatever CADEN had scheduled him for. CADEN's dashboard day runs from 5 AM local time to the next 5 AM local time rather than from midnight to midnight. All events are displayed in the order they start, and all tasks are displayed in the order of due date/time. Types are all mixed, but labeled. Chronological order is more important.
- To the right, the same thing but for the next 7 days. CADEN may schedule his own task blocks at any time before the due date, but he does not move calendar events he did not create. The 7-day view therefore includes future CADEN-scheduled work as well as everything else already on the calendar/task lists.
- in the middle, the chat interface where Sean can chat with CADEN in a CLI
- all chats are embedded by libbie into the central vector db
### Libbie
- Name is short for "Librarian"
- She keeps all CADEN's memories organized in such a way that they are resurfaced when CADEN needs them.
- Manages one vector sqlite DB for everything CADEN will ever do. Memory must not be fragmented across storage.
- Works out of the Project Manager as well. that's also Libbie's domain
- Sean never speaks to Libbie directly, as she represents CADEN's memory. All Sean has to do is chat with CADEN and Libbie's influence will be seen. 
- uses a searxng docker container
  - this means that anything publically available answer should be answerable by CADEN through the chat and is saved for later
- Libbie keeps track of metadata with each memory so that she can look at when and why something was researched/found
### Project Manager App (TBC)
- A registered `TabPane` in the CADEN GUI.
- A place where Sean can keep track of everything that he is working on
- narrow navigation panel to the left listing each project
- the rest of the screen shows the project that has been selected
- Sean selects an entry type from a row of buttons:
  - TODO
  - what-if
  - update
  - comment
- after typing entry, pressing enter key submits it, where it is embedded into the db just like every other kind of input in CADEN. now entries influence the LLM's decisions, as this is literally Sean's thought chain ready to be resurfaced when the situation calls for it
### Thought Dump App (TBC)
- A registered `TabPane` in the CADEN GUI.
- an abyss for Sean to type his thoughts into without shame.
- all thoughts are embedded into the central vector db, just like all chats from the dashboard
- a "hide" button that turns all text on the app's screen (not the full CADEN GUI, just the Thought Dump App) into a cypher so that no one can read over Sean's shoulder
### Sprocket App (TBC)
- vibecoding chat interface
- select app from narrow left navigation panel to edit, or create a new app (these show up as tabs in the CADEN GUI, at the top with Project Manager, Thought Dumper, Sprocket, Dashboard)
- Sean tells sprocket what he wants
- Libbie figures out how to do what Sean is asking CADEN to do and passes that on to sprocket
- Sprocket makes a plan and executes it
- Sprocket learns from failure
  - Every thought emitted by Sprocket is vector searched in the db, and related situations are resurfaced
  - The summary of intent, implementation, and outcome are slipped into the LLM's system prompt