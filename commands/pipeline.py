from abc import ABC, abstractmethod
from functools import cached_property
from typing import ClassVar

import click

from commands.fields import Fields


class Pipeline(ABC):
    """Abstract base class for document processing pipelines."""

    _registry: ClassVar[list["Pipeline"]] = []

    fields_class: type[Fields]

    def __init__(self):
        Pipeline._registry.append(self)

    @property
    @abstractmethod
    def name(self) -> str:
        """Short name for this document type (e.g. 'receipt')."""

    @property
    @abstractmethod
    def default_path(self) -> str:
        """Default vault subdirectory for this document type (e.g. 'Receipts')."""

    @property
    @abstractmethod
    def prompt_template(self) -> str:
        """Prompt template with ``{path}``, ``{filename}``, and ``{ocr_text}`` placeholders."""

    def prompt(self, path: str, ocr_text: str, filename: str = "") -> str:
        """Build the LLM prompt for field extraction."""
        return self.prompt_template.format(
            path=path, filename=filename, ocr_text=ocr_text[:4000]
        )

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
