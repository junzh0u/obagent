from abc import ABC, abstractmethod
from typing import Any


class Fields[K: str](dict[K, str], ABC):
    """Abstract base class for document field containers.

    Each subclass owns its own postprocess, defaults, title, and formatting logic.
    Defaults are applied automatically on construction.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.postprocess()
        self.apply_defaults()

    def postprocess(self) -> None:
        """Post-process extracted fields. Default is no-op."""

    def apply_defaults(self) -> None:
        """Replace falsy field values with empty strings. Override to customize."""
        for key in self:
            if not self[key]:
                self[key] = ""

    def apply_frontmatter(self, frontmatter: dict[K, str]) -> None:
        """Overwrite fields with non-empty frontmatter values."""
        self |= {k: v for k, v in frontmatter.items() if v}

    @abstractmethod
    def make_title(self) -> str:
        """Build a filesystem-safe title from metadata fields."""

    def format_frontmatter(self) -> str:
        """Format fields as YAML frontmatter."""
        fmt = '{}: "{}"'.format
        body = "\n".join(
            fmt(k, v) if v.isdigit() else f"{k}: {v}" for k, v in self.items()
        )
        return f"---\n{body}\n---\n"

    def format_body(self) -> str:
        """Format optional body content. Default returns empty string."""
        return ""
