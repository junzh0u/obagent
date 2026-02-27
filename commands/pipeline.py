from abc import ABC, abstractmethod
from functools import cached_property


class Pipeline(ABC):
    """Abstract base class for document processing pipelines."""

    @property
    @abstractmethod
    def name(self):
        """Short name for this document type (e.g. 'receipt')."""

    @abstractmethod
    def prompt(self, path, ocr_text):
        """Build the LLM prompt for field extraction."""

    def postprocess(self, fields):
        """Post-process extracted fields. Default is no-op."""

    @property
    @abstractmethod
    def field_defaults(self):
        """Dict of default values applied to LLM JSON fields."""

    @abstractmethod
    def make_title(self, fields):
        """Build a filesystem-safe title from metadata fields."""

    @abstractmethod
    def format_frontmatter(self, fields):
        """Format fields as YAML frontmatter."""

    def format_body(self, fields):
        """Format optional body content. Default returns empty string."""
        return ""

    @property
    def help_consume(self):
        return (
            f"Consume {self.name} files into the vault."
            " Accepts files and/or directories."
        )

    @property
    def help_llm(self):
        return f"Extract metadata via LLM from OCR'd {self.name} entries."

    @property
    def help_render(self):
        return f"Render Obsidian notes from LLM-extracted {self.name} metadata."

    @cached_property
    def consume_command(self):
        from commands.consume import make_consume_command

        return make_consume_command(pipeline=self)

    @cached_property
    def llm_command(self):
        from commands.llm import make_llm_command

        return make_llm_command(pipeline=self)

    @cached_property
    def render_command(self):
        from commands.render import make_render_command

        return make_render_command(pipeline=self)
