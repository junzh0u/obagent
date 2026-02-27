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
        """Apply default values to missing/empty fields. Override to customize."""

    def apply_frontmatter(self, frontmatter: dict[K, str]) -> None:
        """Preserve manually-edited frontmatter values into fields.

        Default: overwrite every field that has a non-empty frontmatter value.
        """
        for key, value in frontmatter.items():
            if value:
                self[key] = value

    @abstractmethod
    def make_title(self) -> str:
        """Build a filesystem-safe title from metadata fields."""

    def format_frontmatter(self) -> str:
        """Format fields as YAML frontmatter."""
        body = "\n".join(f"{k}: {v}" for k, v in self.items())
        return f"---\n{body}\n---\n"

    def format_body(self) -> str:
        """Format optional body content. Default returns empty string."""
        return ""
