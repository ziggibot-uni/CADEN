from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal, Mapping, Sequence


MemoryType = Literal["experience", "fact", "rule", "pattern"]
Relevance = Literal["high", "medium", "low"]
OutcomeQuality = Literal["good", "neutral", "bad"]
MemoryRelevance = Literal["confirmed", "rejected", "new_pattern"]


def _tupled(values: Sequence[str]) -> tuple[str, ...]:
	return tuple(str(value).strip() for value in values if str(value).strip())


@dataclass(frozen=True)
class Ligand:
	domain: str
	intent: str
	themes: tuple[str, ...] = field(default_factory=tuple)
	risk: tuple[str, ...] = field(default_factory=tuple)
	outcome_focus: str = ""

	def __post_init__(self) -> None:
		object.__setattr__(self, "domain", self.domain.strip())
		object.__setattr__(self, "intent", self.intent.strip())
		object.__setattr__(self, "themes", _tupled(self.themes))
		object.__setattr__(self, "risk", _tupled(self.risk))
		object.__setattr__(self, "outcome_focus", self.outcome_focus.strip())
		if not self.domain:
			raise ValueError("ligand.domain must not be empty")
		if not self.intent:
			raise ValueError("ligand.intent must not be empty")
		if not self.outcome_focus:
			raise ValueError("ligand.outcome_focus must not be empty")

	@classmethod
	def from_dict(cls, data: Mapping[str, object]) -> "Ligand":
		return cls(
			domain=str(data["domain"]),
			intent=str(data["intent"]),
			themes=tuple(str(item) for item in data.get("themes", ()) or ()),
			risk=tuple(str(item) for item in data.get("risk", ()) or ()),
			outcome_focus=str(data["outcome_focus"]),
		)

	def to_dict(self) -> dict[str, object]:
		return asdict(self)

	def compact_text(self) -> str:
		parts = [self.domain, self.intent, *self.themes, *self.risk, self.outcome_focus]
		return " ".join(part for part in parts if part)


@dataclass(frozen=True)
class MemoryFrame:
	id: str
	type: MemoryType
	domain: str
	tags: tuple[str, ...]
	context: str
	outcome: str
	hooks: tuple[str, ...]
	embedding_text: str

	def __post_init__(self) -> None:
		object.__setattr__(self, "id", self.id.strip())
		object.__setattr__(self, "domain", self.domain.strip())
		object.__setattr__(self, "tags", _tupled(self.tags))
		object.__setattr__(self, "context", self.context.strip())
		object.__setattr__(self, "outcome", self.outcome.strip())
		object.__setattr__(self, "hooks", _tupled(self.hooks))
		object.__setattr__(self, "embedding_text", self.embedding_text.strip())
		if not self.id:
			raise ValueError("memory.id must not be empty")
		if not self.domain:
			raise ValueError("memory.domain must not be empty")
		if not self.context:
			raise ValueError("memory.context must not be empty")
		if not self.outcome:
			raise ValueError("memory.outcome must not be empty")
		if not self.embedding_text:
			raise ValueError("memory.embedding_text must not be empty")

	@classmethod
	def from_dict(cls, data: Mapping[str, object]) -> "MemoryFrame":
		return cls(
			id=str(data["id"]),
			type=str(data["type"]),
			domain=str(data["domain"]),
			tags=tuple(str(item) for item in data.get("tags", ()) or ()),
			context=str(data["context"]),
			outcome=str(data["outcome"]),
			hooks=tuple(str(item) for item in data.get("hooks", ()) or ()),
			embedding_text=str(data["embedding_text"]),
		)

	def to_dict(self) -> dict[str, object]:
		return asdict(self)


@dataclass(frozen=True)
class RecallPacket:
	mem_id: str
	summary: str
	relevance: Relevance
	reason: str = ""

	def __post_init__(self) -> None:
		object.__setattr__(self, "mem_id", self.mem_id.strip())
		object.__setattr__(self, "summary", self.summary.strip())
		object.__setattr__(self, "reason", self.reason.strip())
		if not self.mem_id:
			raise ValueError("recall.mem_id must not be empty")
		if not self.summary:
			raise ValueError("recall.summary must not be empty")

	@classmethod
	def from_dict(cls, data: Mapping[str, object]) -> "RecallPacket":
		return cls(
			mem_id=str(data["mem_id"]),
			summary=str(data["summary"]),
			relevance=str(data["relevance"]),
			reason=str(data.get("reason", "")),
		)

	def to_dict(self) -> dict[str, object]:
		return asdict(self)


@dataclass(frozen=True)
class CadenContext:
	task: str
	recalled_memories: tuple[RecallPacket, ...] = field(default_factory=tuple)

	def __post_init__(self) -> None:
		object.__setattr__(self, "task", self.task.strip())
		object.__setattr__(self, "recalled_memories", tuple(self.recalled_memories))
		if not self.task:
			raise ValueError("context.task must not be empty")

	@classmethod
	def from_dict(cls, data: Mapping[str, object]) -> "CadenContext":
		recalls = tuple(
			RecallPacket.from_dict(item)
			for item in data.get("recalled_memories", ()) or ()
			if isinstance(item, Mapping)
		)
		return cls(task=str(data["task"]), recalled_memories=recalls)

	def to_dict(self) -> dict[str, object]:
		return {
			"task": self.task,
			"recalled_memories": [packet.to_dict() for packet in self.recalled_memories],
		}


@dataclass(frozen=True)
class KnowledgePacket:
	topic: str
	findings: tuple[str, ...] = field(default_factory=tuple)

	def __post_init__(self) -> None:
		object.__setattr__(self, "topic", self.topic.strip())
		object.__setattr__(self, "findings", _tupled(self.findings))
		if not self.topic:
			raise ValueError("knowledge.topic must not be empty")

	@classmethod
	def from_dict(cls, data: Mapping[str, object]) -> "KnowledgePacket":
		return cls(
			topic=str(data["topic"]),
			findings=tuple(str(item) for item in data.get("findings", ()) or ()),
		)

	def to_dict(self) -> dict[str, object]:
		return asdict(self)


@dataclass(frozen=True)
class Evaluation:
	outcome_quality: OutcomeQuality
	memory_relevance: MemoryRelevance

	@classmethod
	def from_dict(cls, data: Mapping[str, object]) -> "Evaluation":
		return cls(
			outcome_quality=str(data["outcome_quality"]),
			memory_relevance=str(data["memory_relevance"]),
		)

	def to_dict(self) -> dict[str, object]:
		return asdict(self)
