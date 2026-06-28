from abc import ABC, abstractmethod
from typing import Any, get_args


class Fields[K: str](dict[K, str], ABC):
    """Abstract base class for document field containers.

    Each subclass owns its own postprocess, defaults, title, and formatting logic.
    Defaults are applied automatically on construction.
    """

    @classmethod
    def expected_keys(cls) -> set[str]:
        """Return the set of field names declared in the Literal type parameter."""
        for base in cls.__orig_bases__:  # type: ignore[attr-defined]
            args = get_args(base)
            if args:
                keys = get_args(args[0])
                if keys:
                    return set(keys)
        return set()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.pop("prompt", None)  # type: ignore[arg-type]
        self.postprocess()
        self.apply_defaults()

    def postprocess(self) -> None:
        """Post-process extracted fields. Default is no-op."""

    def apply_defaults(self) -> None:
        """Replace falsy field values with empty strings. Override to customize."""
        for key in self:
            if not self[key]:
                self[key] = ""

    def apply_frontmatter(self, frontmatter: dict[str, str]) -> None:
        """Overwrite fields with non-empty frontmatter values."""
        for k in self:
            if k in frontmatter and frontmatter[k]:
                self[k] = frontmatter[k]

    def fill_gaps(self, frontmatter: dict[str, str]) -> None:
        """Fill empty fields with values from frontmatter."""
        for k in self:
            if not self[k] and k in frontmatter and frontmatter[k]:
                self[k] = frontmatter[k]

    @abstractmethod
    def make_title(self) -> str:
        """Build a filesystem-safe title from metadata fields."""

    def format_frontmatter(self, *, consumed_at: str = "", notion_id: str = "") -> str:
        """Format fields as YAML frontmatter.

        ``notion_id`` (the linked Notion page id, assigned by ``obagent notion``)
        is emitted only when present, so unsynced notes stay clean. It is never
        derived — render only carries it forward across re-renders.
        """
        fmt = '{}: "{}"'.format
        body = "\n".join(
            fmt(k, v) if v.isdigit() else f"{k}: {v}" for k, v in self.items()
        )
        extra = f"\nnotion_id: {notion_id}" if notion_id else ""
        return f"---\n{body}\nconsumed_at: {consumed_at}{extra}\n---\n"

    def format_body(self) -> str:
        """Format optional body content. Default returns empty string."""
        return ""
