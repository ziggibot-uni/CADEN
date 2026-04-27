"""Sprocket planning service.

This is an initial implementation that can:
- gather a Libbie brief for a build request
- ask the local model for a concrete implementation plan
- persist attempt traces into central memory
"""

from __future__ import annotations

from dataclasses import dataclass
import ast
import os
import re
import subprocess
import sqlite3
from statistics import mean
from typing import Sequence

from ..errors import SprocketError
from ..libbie.retrieve import render_recall_packets, recall_packets_for_task
from ..libbie.store import write_event


SPROCKET_SYSTEM = """You are Sprocket, CADEN's build planner.\nReturn a practical implementation plan with concise numbered steps.\nInclude risks and a verification checklist.\nDo not output code fences unless code is required.\n"""

_NON_PYTHON_LANGUAGE_RE = re.compile(
    r"\b(javascript|typescript|java|c\+\+|c#|rust|go|golang|swift|kotlin|php|ruby)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SprocketBrief:
    query: str
    memory_excerpt: str


@dataclass(frozen=True)
class SprocketPlan:
    brief: SprocketBrief
    plan_text: str


class SprocketService:
    def __init__(self, conn: sqlite3.Connection, llm, embedder, searxng=None) -> None:
        self._conn = conn
        self._llm = llm
        self._embedder = embedder
        self._searxng = searxng

    def build_brief(self, query: str) -> SprocketBrief:
        q = query.strip()
        if not q:
            raise SprocketError("sprocket query must not be empty")
        self._assert_python_only_query(q)
        _, context, _ = recall_packets_for_task(
            self._conn,
            q,
            self._embedder,
            sources=(
                "lesson_learned",
                "project_entry",
                "sean_chat",
                "task",
                "prediction",
                "residual",
            ),
            k=12,
        )
        excerpt = render_recall_packets(context.recalled_memories, include_reason=True)
        if not context.recalled_memories and self._searxng is not None:
            try:
                hits = self._searxng.search(q, limit=3)
            except Exception as e:
                raise SprocketError(f"failed to enrich sprocket brief from SearXNG: {e}") from e
            hit_lines = [hit.summary_text() for hit in hits]
            if hit_lines:
                excerpt += "\n\nweb>\n" + "\n".join(f"- {line}" for line in hit_lines)
        return SprocketBrief(query=q, memory_excerpt=excerpt)

    def propose_plan(self, query: str) -> SprocketPlan:
        brief = self.build_brief(query)
        thought_context = self._resurface_related_for_thoughts(brief.query)
        summaries = self.recent_intent_implementation_outcome_summaries(limit=5)
        failure_lessons = self.failure_lessons(limit=5)
        approach = self._choose_approach(
            brief,
            has_failure_lessons=bool(failure_lessons),
        )
        system_prompt = self._compose_system_prompt(
            summaries=summaries,
            failure_lessons=failure_lessons,
        )
        thought_section = ""
        if thought_context:
            thought_lines = []
            for index, (thought, resurfaced) in enumerate(thought_context, start=1):
                thought_lines.append(f"{index}. thought: {thought}\nrelated:\n{resurfaced}")
            thought_section = "\n\nThought retrieval:\n" + "\n\n".join(thought_lines)
        user_prompt = (
            "Request:\n"
            + brief.query
            + "\n\nRelevant memory:\n"
            + brief.memory_excerpt
            + thought_section
            + "\n\nPreferred implementation approach:\n"
            + approach
            + "\n\nReturn a concrete execution plan."
        )
        try:
            plan_text = self._llm.chat(system_prompt, user_prompt, temperature=0.3)
        except Exception as e:  # routed to loud subsystem-specific error
            raise SprocketError(f"failed to generate sprocket plan: {e}") from e

        self._persist_attempt(
            brief,
            plan_text,
            approach=approach,
            thought_count=len(thought_context),
            summary_count=len(summaries),
            used_failure_lessons=bool(failure_lessons),
        )
        return SprocketPlan(brief=brief, plan_text=plan_text.strip())

    def propose_and_execute(
        self,
        query: str,
        *,
        script_path: str,
        scratch_dir: str,
        timeout_seconds: int = 30,
    ) -> tuple[SprocketPlan, int, str, str]:
        plan = self.propose_plan(query)
        code, out, err = self.run_in_sandbox(
            script_path=script_path,
            scratch_dir=scratch_dir,
            timeout_seconds=timeout_seconds,
        )
        execution_text = (
            f"Sprocket execution: query={query}; script={script_path}; exit={code}"
        )
        write_event(
            self._conn,
            source="sprocket_execution",
            raw_text=execution_text,
            embedding=self._embedder.embed(execution_text),
            meta={
                "trigger": "sprocket_execute",
                "query": query,
                "script_path": script_path,
                "scratch_dir": scratch_dir,
                "exit_code": int(code),
            },
        )
        self.record_intent_implementation_outcome(
            intent=query,
            implementation=plan.plan_text,
            outcome=f"exit={code}; stdout={(out or '').strip()[:240]}; stderr={(err or '').strip()[:240]}",
            success=(code == 0),
        )
        self.record_attempt_outcome(
            source="sandbox",
            attempt_count=1,
            success=(code == 0),
            quality_score=1.0 if code == 0 else 0.0,
        )
        if code != 0:
            details = err.strip() or "no stderr"
            raise SprocketError(f"sprocket execution failed: exit={code}; {details}")
        return plan, code, out, err

    def _choose_approach(self, brief: SprocketBrief, *, has_failure_lessons: bool) -> str:
        if has_failure_lessons:
            return "from_scratch_with_strict_verification"
        if brief.memory_excerpt.strip() and brief.memory_excerpt.strip() != "(no recalled memories)":
            return "copy_and_tweak"
        return "from_scratch"

    def _compose_system_prompt(
        self,
        *,
        summaries: Sequence[str],
        failure_lessons: Sequence[str],
    ) -> str:
        blocks = [SPROCKET_SYSTEM.strip()]
        if summaries:
            blocks.append(
                "Recent intent / implementation / outcome summaries:\n"
                + "\n".join(f"- {line}" for line in summaries)
            )
        if failure_lessons:
            blocks.append(
                "Failure lessons to avoid repeating:\n"
                + "\n".join(f"- {line}" for line in failure_lessons)
            )
        return "\n\n".join(blocks)

    def _derive_thoughts(self, query: str) -> list[str]:
        chunks = re.split(r"[\n.;]+|\band\b", query, flags=re.IGNORECASE)
        cleaned = [chunk.strip() for chunk in chunks if chunk.strip()]
        ordered_unique: list[str] = []
        seen: set[str] = set()
        for item in cleaned:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered_unique.append(item)
            if len(ordered_unique) >= 6:
                break
        if not ordered_unique:
            ordered_unique = [query.strip()]
        return ordered_unique

    def _resurface_related_for_thoughts(self, query: str) -> list[tuple[str, str]]:
        thought_context: list[tuple[str, str]] = []
        for thought in self._derive_thoughts(query):
            _ligand, context, _ = recall_packets_for_task(
                self._conn,
                thought,
                self._embedder,
                sources=(
                    "lesson_learned",
                    "project_entry",
                    "sean_chat",
                    "task",
                    "prediction",
                    "residual",
                    "sprocket_summary",
                    "sprocket_outcome",
                    "sprocket_attempt",
                ),
                k=8,
            )
            resurfaced = render_recall_packets(context.recalled_memories, include_reason=True)
            thought_context.append((thought, resurfaced))
            text = f"Sprocket thought: {thought}\nRelated:\n{resurfaced}"
            write_event(
                self._conn,
                source="sprocket_thought",
                raw_text=text,
                embedding=self._embedder.embed(text),
                meta={
                    "trigger": "sprocket_thought_recall",
                    "thought": thought,
                    "related_count": len(context.recalled_memories),
                },
            )
        return thought_context

    def _assert_python_only_query(self, query: str) -> None:
        match = _NON_PYTHON_LANGUAGE_RE.search(query)
        if match is None:
            return
        language = match.group(1)
        raise SprocketError(
            f"sprocket supports Python-only planning requests (got non-Python language: {language})"
        )

    def _persist_attempt(
        self,
        brief: SprocketBrief,
        plan_text: str,
        *,
        approach: str,
        thought_count: int,
        summary_count: int,
        used_failure_lessons: bool,
    ) -> None:
        text = (
            f"Sprocket request: {brief.query}\n"
            f"Plan:\n{plan_text.strip()}"
        )
        emb: Sequence[float] = self._embedder.embed(text)
        write_event(
            self._conn,
            source="sprocket_attempt",
            raw_text=text,
            embedding=emb,
            meta={
                "query": brief.query,
                "trigger": "sprocket_plan",
                "approach": approach,
                "thought_count": int(thought_count),
                "summary_count": int(summary_count),
                "used_failure_lessons": bool(used_failure_lessons),
            },
        )

    def record_intent_implementation_outcome(
        self,
        *,
        intent: str,
        implementation: str,
        outcome: str,
        success: bool,
    ) -> int:
        intent_text = intent.strip()
        implementation_text = implementation.strip()
        outcome_text = outcome.strip()
        if not intent_text:
            raise SprocketError("intent summary must not be empty")
        text = (
            f"Intent: {intent_text}\n"
            f"Implementation: {implementation_text}\n"
            f"Outcome: {outcome_text}"
        )
        return write_event(
            self._conn,
            source="sprocket_summary",
            raw_text=text,
            embedding=self._embedder.embed(text),
            meta={
                "intent": intent_text,
                "implementation": implementation_text,
                "outcome": outcome_text,
                "success": bool(success),
                "trigger": "sprocket_summary",
            },
        )

    def recent_intent_implementation_outcome_summaries(self, *, limit: int = 5) -> tuple[str, ...]:
        rows = self._conn.execute(
            """
            SELECT i.value AS intent, imp.value AS implementation, o.value AS outcome
            FROM event_metadata AS i
            JOIN event_metadata AS imp
              ON imp.event_id = i.event_id
            JOIN event_metadata AS o
              ON o.event_id = i.event_id
            JOIN events AS e
              ON e.id = i.event_id
            WHERE e.source='sprocket_summary'
              AND i.key='intent'
              AND imp.key='implementation'
              AND o.key='outcome'
            ORDER BY e.id DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
        summaries = [
            f"intent={str(row['intent']).strip()} | implementation={str(row['implementation']).strip()[:120]} | outcome={str(row['outcome']).strip()[:120]}"
            for row in rows
        ]
        return tuple(summaries)

    def failure_lessons(self, *, limit: int = 5) -> tuple[str, ...]:
        rows = self._conn.execute(
            """
            SELECT s.value AS source_name, a.value AS attempt_count, q.value AS quality_score, ok.value AS success
            FROM event_metadata AS s
            JOIN event_metadata AS a
              ON a.event_id = s.event_id
            JOIN event_metadata AS q
              ON q.event_id = s.event_id
            JOIN event_metadata AS ok
              ON ok.event_id = s.event_id
            JOIN events AS e
              ON e.id = s.event_id
            WHERE e.source='sprocket_outcome'
              AND s.key='source_name'
              AND a.key='attempt_count'
              AND q.key='quality_score'
              AND ok.key='success'
            ORDER BY e.id DESC
            LIMIT 100
            """
        ).fetchall()

        lessons: list[str] = []
        for row in rows:
            quality = float(row["quality_score"])
            success_flag = str(row["success"]).lower() in {"true", "1"}
            if success_flag and quality >= 0.7:
                continue
            source = str(row["source_name"])
            attempts = int(float(row["attempt_count"]))
            lessons.append(
                f"source={source} failed_or_low_quality at attempts={attempts}, quality={quality:.2f}; add stricter verification"
            )
            if len(lessons) >= max(1, int(limit)):
                break
        return tuple(lessons)

    def store_code_memory(self, *, code_text: str, context: str = "") -> int:
        raw_code = code_text.strip()
        if not raw_code:
            raise SprocketError("sprocket code memory must not be empty")
        try:
            tree = ast.parse(raw_code)
        except SyntaxError as e:
            raise SprocketError(f"sprocket code memory parse failed: {e}") from e

        ast_dump = ast.dump(tree, include_attributes=False, indent=2)
        text = (
            "Sprocket code memory\n"
            + (f"Context: {context.strip()}\n" if context.strip() else "")
            + "Code:\n"
            + raw_code
        )
        emb: Sequence[float] = self._embedder.embed(text)
        return write_event(
            self._conn,
            source="sprocket_code_memory",
            raw_text=text,
            embedding=emb,
            meta={
                "trigger": "sprocket_code_memory",
                "ast": ast_dump,
                "format": "python_ast_plus_text",
            },
        )

    def run_in_sandbox(
        self,
        *,
        script_path: str,
        scratch_dir: str,
        timeout_seconds: int = 30,
    ) -> tuple[int, str, str]:
        cmd = [
            "firejail",
            "--net=none",
            f"--private={scratch_dir}",
            "--quiet",
            "python",
            script_path,
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except FileNotFoundError as e:
            raise SprocketError(f"sandbox execution failed: {e}") from e
        except subprocess.TimeoutExpired as e:
            raise SprocketError(f"sandbox execution timed out after {timeout_seconds}s") from e
        return int(result.returncode), str(result.stdout), str(result.stderr)

    def retrieve_code_memories(
        self,
        *,
        query: str,
        query_code: str | None = None,
        k: int = 5,
    ) -> list[dict[str, object]]:
        q = query.strip()
        if not q:
            raise SprocketError("sprocket code memory query must not be empty")

        _ligand, context, _ = recall_packets_for_task(
            self._conn,
            q,
            self._embedder,
            sources=("sprocket_code_memory",),
            k=max(k, 5),
        )
        semantic = {
            packet.mem_id: {
                "mem_id": packet.mem_id,
                "summary": packet.summary,
                "semantic_relevance": packet.relevance,
                "semantic_reason": packet.reason,
                "structural_score": 0.0,
            }
            for packet in context.recalled_memories
        }

        query_nodes: set[str] = set()
        if query_code is not None and query_code.strip():
            try:
                tree = ast.parse(query_code)
                query_nodes = {type(node).__name__ for node in ast.walk(tree)}
            except SyntaxError as e:
                raise SprocketError(f"structural query parse failed: {e}") from e

        rows = self._conn.execute(
            """
            SELECT m.memory_key, em.value AS ast_dump
            FROM memories AS m
            JOIN event_metadata AS em
              ON em.event_id = m.event_id
             AND em.key = 'ast'
            WHERE m.source='sprocket_code_memory'
            ORDER BY m.id DESC
            LIMIT ?
            """,
            (max(k * 3, 10),),
        ).fetchall()

        for row in rows:
            mem_id = str(row["memory_key"])
            if mem_id not in semantic:
                semantic[mem_id] = {
                    "mem_id": mem_id,
                    "summary": "",
                    "semantic_relevance": "low",
                    "semantic_reason": "",
                    "structural_score": 0.0,
                }
            if query_nodes:
                ast_dump = str(row["ast_dump"] or "")
                cand_nodes = {
                    token
                    for token in query_nodes
                    if token in ast_dump
                }
                score = len(cand_nodes) / max(1, len(query_nodes))
                semantic[mem_id]["structural_score"] = float(score)

        ranked = sorted(
            semantic.values(),
            key=lambda item: (
                float(item["structural_score"]),
                1 if item["semantic_relevance"] == "high" else 0,
                1 if item["semantic_relevance"] == "medium" else 0,
            ),
            reverse=True,
        )
        return ranked[:k]

    def learned_attempt_budget(self) -> int:
        rows = self._conn.execute(
            """
            SELECT value
            FROM event_metadata
            WHERE key='attempt_count'
            ORDER BY id DESC
            LIMIT 100
            """
        ).fetchall()
        values = [int(row["value"]) for row in rows if str(row["value"]).isdigit()]
        if not values:
            return 3
        return max(1, min(12, int(round(mean(values)))))

    def record_attempt_outcome(
        self,
        *,
        source: str,
        attempt_count: int,
        success: bool,
        quality_score: float,
    ) -> int:
        text = (
            f"Sprocket outcome: source={source} attempts={attempt_count} "
            f"success={success} quality={quality_score:.3f}"
        )
        return write_event(
            self._conn,
            source="sprocket_outcome",
            raw_text=text,
            embedding=self._embedder.embed(text),
            meta={
                "source_name": source,
                "attempt_count": int(attempt_count),
                "success": bool(success),
                "quality_score": float(quality_score),
                "trigger": "sprocket_outcome",
            },
        )

    def source_quality_scores(self) -> dict[str, float]:
        rows = self._conn.execute(
            """
            SELECT s.value AS source_name, q.value AS quality_score
            FROM event_metadata AS s
            JOIN event_metadata AS q
              ON q.event_id = s.event_id
            JOIN events AS e
              ON e.id = s.event_id
            WHERE e.source='sprocket_outcome'
              AND s.key='source_name'
              AND q.key='quality_score'
            """
        ).fetchall()
        agg: dict[str, list[float]] = {}
        for row in rows:
            source = str(row["source_name"])
            score = float(row["quality_score"])
            agg.setdefault(source, []).append(score)
        return {
            source: float(mean(scores))
            for source, scores in agg.items()
        }

    def derive_abstraction_templates(self, *, min_support: int = 2) -> tuple[str, ...]:
        rows = self._conn.execute(
            """
            SELECT s.value AS source_name, q.value AS quality_score
            FROM event_metadata AS s
            JOIN event_metadata AS q
              ON q.event_id = s.event_id
            JOIN events AS e
              ON e.id = s.event_id
            WHERE e.source='sprocket_outcome'
              AND s.key='source_name'
              AND q.key='quality_score'
            ORDER BY e.id DESC
            """
        ).fetchall()
        clusters: dict[str, list[float]] = {}
        for row in rows:
            source = str(row["source_name"])
            score = float(row["quality_score"])
            if score < 0.7:
                continue
            clusters.setdefault(source, []).append(score)

        templates: list[str] = []
        for source, scores in clusters.items():
            if len(scores) < min_support:
                continue
            templates.append(
                f"Template from {source}: pattern with mean_quality={mean(scores):.2f}"
            )
        return tuple(sorted(templates))

    def propose_integration(self, *, app_name: str, module_path: str) -> int:
        text = f"Integration proposal: {app_name} -> {module_path}"
        return write_event(
            self._conn,
            source="sprocket_integration_proposal",
            raw_text=text,
            embedding=self._embedder.embed(text),
            meta={
                "app_name": app_name,
                "module_path": module_path,
                "status": "proposed",
                "trigger": "sprocket_integration",
            },
        )

    def accept_integration(
        self,
        *,
        proposal_event_id: int,
        smoke_gate,
    ) -> int:
        row = self._conn.execute(
            "SELECT raw_text FROM events WHERE id=? AND source='sprocket_integration_proposal'",
            (proposal_event_id,),
        ).fetchone()
        if row is None:
            raise SprocketError(f"integration proposal {proposal_event_id} does not exist")

        ok = bool(smoke_gate())
        if not ok:
            raise SprocketError("integration smoke gate failed")
        text = f"Integration accepted from proposal #{proposal_event_id}"
        return write_event(
            self._conn,
            source="sprocket_integration_accepted",
            raw_text=text,
            embedding=self._embedder.embed(text),
            meta={
                "proposal_event_id": proposal_event_id,
                "status": "accepted",
                "smoke_gate": "passed",
                "trigger": "sprocket_integration",
            },
        )

    def guardrail_validate_target(self, *, target_path: str) -> None:
        path = target_path.strip()
        if not path:
            raise SprocketError("target_path must not be empty")
        if os.path.exists(path):
            raise SprocketError("guardrail: modifying existing CADEN code is forbidden")

    def ast_copy_and_tweak(
        self,
        *,
        base_code: str,
        function_name: str,
        new_return_expr: str,
    ) -> str:
        try:
            tree = ast.parse(base_code)
        except SyntaxError as e:
            raise SprocketError(f"base code parse failed: {e}") from e
        try:
            new_expr = ast.parse(new_return_expr, mode="eval").body
        except SyntaxError as e:
            raise SprocketError(f"new return expression parse failed: {e}") from e

        class _Tweaker(ast.NodeTransformer):
            def visit_FunctionDef(self, node: ast.FunctionDef):
                if node.name == function_name:
                    node.body = [ast.Return(value=new_expr)]
                return self.generic_visit(node)

        tweaked = _Tweaker().visit(tree)
        ast.fix_missing_locations(tweaked)
        try:
            return ast.unparse(tweaked)
        except Exception as e:
            raise SprocketError(f"failed to render tweaked code: {e}") from e
