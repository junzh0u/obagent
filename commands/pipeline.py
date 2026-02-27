from abc import ABC, abstractmethod
from functools import cached_property
from typing import cast

import click


class Pipeline[T](ABC):
    """Abstract base class for document processing pipelines."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short name for this document type (e.g. 'receipt')."""

    @abstractmethod
    def prompt(self, path: str, ocr_text: str) -> str:
        """Build the LLM prompt for field extraction."""

    def postprocess(self, fields: T) -> None:
        """Post-process extracted fields. Default is no-op."""

    def apply_defaults(self, fields: T) -> None:
        """Apply default values to missing/empty fields. Override to customize."""

    def apply_frontmatter(self, fields: T, frontmatter: dict[str, str]) -> None:
        """Preserve manually-edited frontmatter values into fields.

        Default: overwrite every field that has a non-empty frontmatter value.
        """
        for key, value in frontmatter.items():
            if value:
                cast(dict[str, str], fields)[key] = value

    @abstractmethod
    def make_title(self, fields: T) -> str:
        """Build a filesystem-safe title from metadata fields."""

    def format_frontmatter(self, fields: T) -> str:
        """Format fields as YAML frontmatter."""
        d = cast(dict[str, str], fields)
        body = "\n".join(f"{k}: {v}" for k, v in d.items())
        return f"---\n{body}\n---\n"

    def format_body(self, fields: T) -> str:
        """Format optional body content. Default returns empty string."""
        return ""

    @property
    def help_consume(self) -> str:
        return (
            f"Consume {self.name} files into the vault."
            " Accepts files and/or directories."
        )

    @property
    def help_llm(self) -> str:
        return f"Extract metadata via LLM from OCR'd {self.name} entries."

    @property
    def help_render(self) -> str:
        return f"Render Obsidian notes from LLM-extracted {self.name} metadata."

    @cached_property
    def consume_command(self) -> click.Command:
        from commands.consume import make_consume_command

        return make_consume_command(pipeline=self)

    @cached_property
    def llm_command(self) -> click.Command:
        from commands.llm import make_llm_command

        return make_llm_command(pipeline=self)

    @cached_property
    def render_command(self) -> click.Command:
        from commands.render import make_render_command

        return make_render_command(pipeline=self)
