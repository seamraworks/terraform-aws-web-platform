from dataclasses import dataclass, field
from typing import Literal, Protocol

SCHEMA_VERSION = 1
DECISION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"decision": {"type": "string", "enum": ["keep", "spam", "review"]},
                   "reason": {"type": "string"}},
    "required": ["decision", "reason"],
}


class ProviderError(Exception):
    """No reliable decision was obtained. Callers must retain the content."""


@dataclass(frozen=True)
class ModerationRequest:
    text: str
    context: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.text, str) or not isinstance(self.context, dict):
            raise ValueError("Expected text and a context object")
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in self.context.items()):
            raise ValueError("Context keys and values must be strings")

    def to_dict(self):
        return {"schema_version": SCHEMA_VERSION, "text": self.text, "context": self.context}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) - {"schema_version", "text", "context"}:
            raise ValueError("Invalid request fields")
        if value.get("schema_version") != SCHEMA_VERSION or isinstance(value.get("schema_version"), bool):
            raise ValueError("Unsupported moderation schema version")
        return cls(value["text"], value.get("context", {}))


@dataclass(frozen=True)
class ModerationResult:
    decision: Literal["keep", "spam", "review"]
    reason: str
    provider: str = ""
    model: str = ""
    policy_id: str = ""

    def __post_init__(self):
        if self.decision not in {"keep", "spam", "review"}:
            raise ProviderError("Invalid moderation decision")
        if not isinstance(self.reason, str) or not 1 <= len(self.reason) <= 1000:
            raise ProviderError("Invalid moderation reason")
        if not all(isinstance(v, str) and len(v) <= 256 for v in (self.provider, self.model, self.policy_id)):
            raise ProviderError("Invalid provider metadata")

    def to_dict(self):
        return {"schema_version": SCHEMA_VERSION, "decision": self.decision, "reason": self.reason,
                "provider": self.provider, "model": self.model, "policy_id": self.policy_id}


class ModerationProvider(Protocol):
    def classify(self, request: ModerationRequest) -> ModerationResult: ...
