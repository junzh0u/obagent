from abc import ABC, abstractmethod
from functools import cached_property

import click

from commands.fields import Fields


class Pipeline(ABC):
    """Abstract base class for document processing pipelines."""

    fields_class: type[Fields]

    @property
    @abstractmethod
    def name(self) -> str:
        """Short name for this document type (e.g. 'receipt')."""

    @abstractmethod
    def prompt(self, path: str, ocr_text: str) -> str:
        """Build the LLM prompt for field extraction."""

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
