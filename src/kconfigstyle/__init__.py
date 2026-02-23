#!/usr/bin/env python3
"""
Kconfig file linter and formatter with support for Zephyr and ESP-IDF styles.

This implementation uses a parser to build an AST, then formats by traversing the tree.
"""

import argparse
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

try:
    from importlib.metadata import version

    __version__ = version("kconfigstyle")
except Exception:
    __version__ = "unknown"


@dataclass
class LinterConfig:
    """Configuration for the Kconfig linter."""

    use_spaces: bool = False  # If False, use tabs
    primary_indent_spaces: int = 4
    help_indent_spaces: int = 2
    max_line_length: int = 100
    max_option_name_length: int = 50
    min_prefix_length: int = 3
    enforce_uppercase_configs: bool = False
    indent_sub_items: bool = False
    consolidate_empty_lines: bool = False
    reflow_help_text: bool = False

    @classmethod
    def zephyr_preset(cls) -> "LinterConfig":
        """Create a Zephyr style preset configuration."""
        return cls(
            use_spaces=False,
            primary_indent_spaces=4,
            help_indent_spaces=2,
            max_line_length=100,
            max_option_name_length=50,
            enforce_uppercase_configs=False,
            indent_sub_items=False,
            consolidate_empty_lines=False,
        )

    @classmethod
    def espidf_preset(cls) -> "LinterConfig":
        """Create an ESP-IDF style preset configuration."""
        return cls(
            use_spaces=True,
            primary_indent_spaces=4,
            help_indent_spaces=4,
            max_line_length=120,
            max_option_name_length=50,
            min_prefix_length=3,
            enforce_uppercase_configs=True,
            indent_sub_items=True,
            consolidate_empty_lines=False,
        )


@dataclass
class LintIssue:
    """Represents a linting issue."""

    line_number: int
    column: int | None
    severity: str  # 'error' or 'warning'
    message: str

    def __str__(self):
        col_str = f":{self.column}" if self.column is not None else ""
        return f"Line {self.line_number}{col_str}: [{self.severity}] {self.message}"


# AST Node Types


@dataclass
class ASTNode:
    """Base class for AST nodes."""

    line_number: int = 0
    inline_comment: str = ""  # Inline comment (e.g., "# comment")


@dataclass
class Comment(ASTNode):
    """Comment line."""

    line_number: int = 0
    text: str = ""  # Without the leading #


@dataclass
class EmptyLine(ASTNode):
    """Empty line."""

    line_number: int = 0


@dataclass
class HelpText(ASTNode):
    """Help text block."""

    line_number: int = 0
    lines: list[str] = field(default_factory=list)  # Stripped text lines


@dataclass
class ConfigOption(ASTNode):
    """A config option like 'bool', 'default', 'depends on', etc."""

    line_number: int = 0
    option_type: str = ""  # 'bool', 'default', 'depends_on', 'select', etc.
    value: str = ""  # The rest of the line
    condition: str = ""  # Optional 'if' condition


@dataclass
class ConfigEntry(ASTNode):
    """A config or menuconfig entry."""

    line_number: int = 0
    config_type: Literal["config", "menuconfig"] = "config"
    name: str = ""
    options: list[ASTNode] = field(
        default_factory=list
    )  # ConfigOption, Comment, HelpText


@dataclass
class ChoiceEntry(ASTNode):
    """A choice block."""

    line_number: int = 0
    name: str = ""  # Optional name
    options: list[ASTNode] = field(
        default_factory=list
    )  # ConfigOption, Comment, HelpText
    entries: list[ASTNode] = field(
        default_factory=list
    )  # Config entries, if blocks, etc. within choice


@dataclass
class MenuEntry(ASTNode):
    """A menu block."""

    line_number: int = 0
    title: str = ""
    depends: list[str] = field(default_factory=list)
    statements: list[ASTNode] = field(default_factory=list)


@dataclass
class IfBlock(ASTNode):
    """An if/endif block."""

    line_number: int = 0
    condition: str = ""
    statements: list[ASTNode] = field(default_factory=list)


@dataclass
class SourceStatement(ASTNode):
    """A source/rsource statement."""

    line_number: int = 0
    source_type: str = "source"  # 'source', 'rsource', 'osource', 'orsource'
    path: str = ""


@dataclass
class CommentStatement(ASTNode):
    """A 'comment' statement (visible comment in menuconfig)."""

    line_number: int = 0
    text: str = ""
    depends: list[str] = field(default_factory=list)


@dataclass
class UnknownLine(ASTNode):
    """An unknown/unrecognized line that should be preserved as-is."""

    line_number: int = 0
    text: str = ""


class KconfigParser:
    """Parser for Kconfig files."""

    def __init__(self):
        self.lines: list[str] = []
        self.pos: int = 0
        self.current_line_num: int = 0

    def parse(self, content: str) -> list[ASTNode]:
        """Parse Kconfig content into an AST."""
        # First, join continuation lines
        self.lines = self._join_continuation_lines(content.splitlines())
        self.pos = 0
        self.current_line_num = 0

        statements = []
        while self.pos < len(self.lines):
            stmt = self._parse_statement()
            if stmt:
                statements.append(stmt)
            else:
                self.pos += 1
                self.current_line_num += 1

        return statements

    def _join_continuation_lines(self, lines: list[str]) -> list[str]:
        """Join lines that end with backslash continuation."""
        result = []
        i = 0

        while i < len(lines):
            line = lines[i]

            # Check if this line ends with backslash
            if line.rstrip().endswith("\\"):
                # Collect all continuation lines
                joined = line.rstrip()[:-1].rstrip()  # Remove \\ and trailing space
                i += 1

                # Keep joining while we have continuations
                while i < len(lines):
                    next_line = lines[i]
                    stripped = next_line.lstrip()

                    if next_line.rstrip().endswith("\\"):
                        # Another continuation
                        joined += " " + stripped[:-1].rstrip()
                        i += 1
                    else:
                        # Last line of continuation
                        joined += " " + stripped
                        i += 1
                        break

                result.append(joined)
            else:
                result.append(line)
                i += 1

        return result

    def _current_line(self) -> str:
        """Get current line."""
        if self.pos >= len(self.lines):
            return ""
        return self.lines[self.pos]

    def _peek_line(self, offset: int = 1) -> str:
        """Peek at a future line."""
        idx = self.pos + offset
        if idx >= len(self.lines):
            return ""
        return self.lines[idx]

    def _advance(self):
        """Move to next line."""
        self.pos += 1
        self.current_line_num += 1

    def _extract_inline_comment(self, line: str) -> tuple[str, str]:
        """Extract inline comment from a line.

        Returns:
            Tuple of (line_without_comment, comment_with_hash)

        Note: This does NOT handle comments inside quoted strings.
        """
        # Simple approach: find # and split there
        # TODO: Handle # inside quoted strings properly
        comment_pos = line.find("#")
        if comment_pos == -1:
            return line, ""

        # Everything before # is the code, everything from # is the comment
        code_part = line[:comment_pos].rstrip()
        comment_part = line[comment_pos:].rstrip()

        return code_part, comment_part

    def _parse_statement(self) -> ASTNode | None:
        """Parse a top-level statement."""
        line = self._current_line()
        stripped = line.lstrip()

        # Empty line
        if not stripped:
            node = EmptyLine(line_number=self.current_line_num)
            self._advance()
            return node

        # Comment
        if stripped.startswith("#"):
            text = stripped[1:].strip() if len(stripped) > 1 else ""
            node = Comment(text=text, line_number=self.current_line_num)
            self._advance()
            return node

        # Config/menuconfig
        if stripped.startswith("config "):
            return self._parse_config_entry()

        if stripped.startswith("menuconfig "):
            return self._parse_menuconfig_entry()

        # Choice
        if stripped.startswith("choice"):
            return self._parse_choice()

        # Menu
        if stripped.startswith("menu "):
            return self._parse_menu()

        # If
        if stripped.startswith("if "):
            return self._parse_if_block()

        # Source statements
        if stripped.startswith(("source ", "rsource ", "osource ", "orsource ")):
            return self._parse_source()

        # Comment statement
        if stripped.startswith("comment "):
            return self._parse_comment_statement()

        # Unknown - preserve as-is
        node = UnknownLine(text=line, line_number=self.current_line_num)
        self._advance()
        return node

    def _parse_config_entry(self) -> ConfigEntry:
        """Parse a config or menuconfig entry."""
        line = self._current_line()
        stripped = line.lstrip()

        # Extract inline comment
        stripped_no_comment, inline_comment = self._extract_inline_comment(stripped)

        if stripped_no_comment.startswith("menuconfig "):
            config_type = "menuconfig"
            name = stripped_no_comment[11:].strip()
        else:
            config_type = "config"
            name = stripped_no_comment[7:].strip()

        node = ConfigEntry(
            config_type=config_type,
            name=name,
            line_number=self.current_line_num,
            inline_comment=inline_comment,
        )
        self._advance()

        # Parse options until we hit a structural keyword or end
        while self.pos < len(self.lines):
            line = self._current_line()
            stripped = line.lstrip()

            # Empty line within config
            if not stripped:
                # Check if next non-empty line is a structural keyword or unindented
                peek_pos = self.pos + 1
                found_content = False
                while peek_pos < len(self.lines):
                    peek_line = self.lines[peek_pos]
                    peek_stripped = peek_line.lstrip()
                    if peek_stripped:  # Found non-empty line
                        # Check if it's structural keyword - always end config
                        if self._is_structural_keyword(peek_stripped):
                            return node
                        # Check if it's unindented - end config unless it's clearly part of config
                        if peek_line[0] not in (" ", "\t"):
                            # After blank lines, unindented content ends the config
                            # (even if it's a comment or config option keyword)
                            return node
                        found_content = True
                        break
                    peek_pos += 1

                # If we didn't find any more content, end the config
                if not found_content:
                    return node

                # Otherwise, this empty line is part of the config
                node.options.append(EmptyLine(line_number=self.current_line_num))
                self._advance()
                continue

            # Structural keywords end the config block
            if self._is_structural_keyword(stripped):
                break

            # Unindented lines: allow config option keywords and comments, but only if not after empty lines
            if line and line[0] not in (" ", "\t"):
                # If this is not a config option keyword or comment, end the block
                if not self._is_config_option_keyword(
                    stripped
                ) and not stripped.startswith("#"):
                    break

            # Comment within config
            if stripped.startswith("#"):
                text = stripped[1:].strip() if len(stripped) > 1 else ""
                node.options.append(
                    Comment(text=text, line_number=self.current_line_num)
                )
                self._advance()
                continue

            # Help block
            if stripped.startswith("help"):
                node.options.append(self._parse_help_block())
                continue

            # Config option
            option = self._parse_config_option()
            if option:
                node.options.append(option)
            else:
                # Unknown line within config - preserve it
                node.options.append(
                    UnknownLine(text=line, line_number=self.current_line_num)
                )
                self._advance()

        return node

    def _parse_menuconfig_entry(self) -> ConfigEntry:
        """Parse a menuconfig entry (similar to config but can be a menu parent)."""
        line = self._current_line()
        stripped = line.lstrip()

        # Extract inline comment
        stripped_no_comment, inline_comment = self._extract_inline_comment(stripped)

        config_type = "menuconfig"
        name = stripped_no_comment[11:].strip()

        node = ConfigEntry(
            config_type=config_type,
            name=name,
            line_number=self.current_line_num,
            inline_comment=inline_comment,
        )
        self._advance()

        # Parse options until we hit a structural keyword or end
        while self.pos < len(self.lines):
            line = self._current_line()
            stripped = line.lstrip()

            # Empty line within config
            if not stripped:
                # Check if next non-empty line is a structural keyword or unindented
                peek_pos = self.pos + 1
                found_content = False
                while peek_pos < len(self.lines):
                    peek_line = self.lines[peek_pos]
                    peek_stripped = peek_line.lstrip()
                    if peek_stripped:  # Found non-empty line
                        # Check if it's structural keyword - always end config
                        if self._is_structural_keyword(peek_stripped):
                            return node
                        # Check if it's unindented - end config unless it's clearly part of config
                        if peek_line[0] not in (" ", "\t"):
                            # After blank lines, unindented content ends the config
                            # (even if it's a comment or config option keyword)
                            return node
                        found_content = True
                        break
                    peek_pos += 1

                # If we didn't find any more content, end the config
                if not found_content:
                    return node

                # Otherwise, this empty line is part of the config
                node.options.append(EmptyLine(line_number=self.current_line_num))
                self._advance()
                continue

            # Structural keywords end the config block
            if self._is_structural_keyword(stripped):
                break

            # Unindented lines: allow config option keywords and comments, but only if not after empty lines
            if line and line[0] not in (" ", "\t"):
                # If this is not a config option keyword or comment, end the block
                if not self._is_config_option_keyword(
                    stripped
                ) and not stripped.startswith("#"):
                    break

            # Comment within config
            if stripped.startswith("#"):
                text = stripped[1:].strip() if len(stripped) > 1 else ""
                node.options.append(
                    Comment(text=text, line_number=self.current_line_num)
                )
                self._advance()
                continue

            # Help block
            if stripped.startswith("help"):
                node.options.append(self._parse_help_block())
                continue

            # Config option
            option = self._parse_config_option()
            if option:
                node.options.append(option)
            else:
                # Unknown line within config - preserve it
                node.options.append(
                    UnknownLine(text=line, line_number=self.current_line_num)
                )
                self._advance()

        return node

    def _is_structural_keyword(self, stripped: str) -> bool:
        """Check if line starts with a structural keyword."""
        keywords = [
            "config ",
            "menuconfig ",
            "choice",
            "endchoice",
            "menu ",
            "endmenu",
            "if ",
            "endif",
            "source ",
            "rsource ",
            "osource ",
            "orsource ",
            "comment ",
            "mainmenu ",
        ]
        return any(stripped.startswith(kw) for kw in keywords)

    def _is_config_option_keyword(self, stripped: str) -> bool:
        """Check if line starts with a config option keyword."""
        keywords = [
            "bool",
            "tristate",
            "string",
            "int",
            "hex",
            "def_bool",
            "def_tristate",
            "prompt",
            "default",
            "depends on",
            "depends",
            "select",
            "imply",
            "range",
            "option",
            "help",
        ]
        return any(stripped.startswith(kw) for kw in keywords)

    def _parse_config_option(self) -> ConfigOption | None:
        """Parse a config option like 'bool', 'default', etc."""
        line = self._current_line()
        stripped = line.lstrip()

        # Extract inline comment
        stripped_no_comment, inline_comment = self._extract_inline_comment(stripped)

        # Match option types
        patterns = {
            "bool": r"^bool(\s+(.*))?$",
            "tristate": r"^tristate(\s+(.*))?$",
            "string": r"^string(\s+(.*))?$",
            "int": r"^int(\s+(.*))?$",
            "hex": r"^hex(\s+(.*))?$",
            "def_bool": r"^def_bool\s+(.+)$",
            "def_tristate": r"^def_tristate\s+(.+)$",
            "prompt": r"^prompt\s+(.+)$",
            "default": r"^default\s+(.+)$",
            "depends_on": r"^depends\s+on\s+(.+)$",
            "select": r"^select\s+(.+)$",
            "imply": r"^imply\s+(.+)$",
            "range": r"^range\s+(.+)$",
            "option": r"^option\s+(.+)$",
        }

        for opt_type, pattern in patterns.items():
            match = re.match(pattern, stripped_no_comment)
            if match:
                if opt_type in ["bool", "tristate", "string", "int", "hex"]:
                    # For type definitions, group 2 contains the optional prompt
                    value = ""
                    if match.groups() and len(match.groups()) >= 2:
                        value = match.group(2) if match.group(2) else ""
                else:
                    value = match.group(1) if match.groups() else ""

                # Check for 'if' condition
                condition = ""
                if value and " if " in value:
                    parts = value.rsplit(" if ", 1)
                    value = parts[0].strip()
                    condition = parts[1].strip()

                node = ConfigOption(
                    option_type=opt_type,
                    value=value.strip() if value else "",
                    condition=condition,
                    line_number=self.current_line_num,
                    inline_comment=inline_comment,
                )
                self._advance()
                return node

        # Unknown option type - skip
        self._advance()
        return None

    def _parse_help_block(self) -> HelpText:
        """Parse a help text block."""
        node = HelpText(line_number=self.current_line_num)
        self._advance()  # Skip 'help' line

        # Determine help text indentation from first non-empty line
        help_indent = None

        while self.pos < len(self.lines):
            line = self._current_line()
            stripped = line.lstrip()

            # Empty line within help - check what follows
            if not stripped:
                # Peek at next line to see if help continues
                next_line = self._peek_line()
                if next_line:
                    next_stripped = next_line.lstrip()
                    # If next line is unindented structural keyword, end help
                    if next_line[0] not in (" ", "\t") and self._is_structural_keyword(
                        next_stripped
                    ):
                        break
                    # If next line is unindented and not empty, end help
                    if next_line[0] not in (" ", "\t") and next_line.strip():
                        break

                node.lines.append("")
                self._advance()
                continue

            # Determine indentation from first help text line
            if help_indent is None:
                # Count leading whitespace
                if stripped:
                    help_indent = len(line) - len(stripped)

                    # Validate that help text has proper indentation
                    # Help text must be indented more than structural keywords (which are at column 0)
                    # Exception: if the line is a structural keyword itself, it means the help block is empty
                    # which is valid
                    if help_indent == 0 and not self._is_structural_keyword(stripped):
                        raise ValueError(
                            f"Line {self.current_line_num}: Help text must be indented. "
                            f"The first line of help text has no indentation, making it "
                            f"ambiguous where the help block ends."
                        )

            # Check if this line is part of help text
            if help_indent is not None:
                current_indent = len(line) - len(stripped) if stripped else 0

                # If line is indented at or past help indent level, it's help text
                # (even if it looks like a structural keyword)
                if stripped and current_indent >= help_indent:
                    node.lines.append(stripped)
                    self._advance()
                # Empty line - could be paragraph break
                elif not stripped:
                    node.lines.append("")
                    self._advance()
                else:
                    # Less indented than help text
                    # Check if it's a structural keyword - if so, end help
                    if self._is_structural_keyword(stripped):
                        break
                    # Otherwise, less indented non-keyword - also ends help block
                    break
            else:
                # No help text found yet, but line has content - not help
                break

        # Consolidate consecutive empty lines in help text
        consolidated_lines = []
        prev_was_empty = False
        for line in node.lines:
            if not line:
                if not prev_was_empty:
                    consolidated_lines.append(line)
                    prev_was_empty = True
            else:
                consolidated_lines.append(line)
                prev_was_empty = False
        node.lines = consolidated_lines

        # Strip trailing empty lines
        while node.lines and not node.lines[-1]:
            node.lines.pop()

        return node

    def _parse_choice(self) -> ChoiceEntry:
        """Parse a choice block."""
        line = self._current_line()
        stripped = line.lstrip()

        # Extract optional name
        name = ""
        if len(stripped) > 6 and stripped[6:].strip():
            name = stripped[6:].strip()

        node = ChoiceEntry(name=name, line_number=self.current_line_num)
        self._advance()

        # Parse until 'endchoice'
        while self.pos < len(self.lines):
            line = self._current_line()
            stripped = line.lstrip()

            if stripped.startswith("endchoice"):
                # Extract inline comment if present
                _, comment = self._extract_inline_comment(line)
                node.inline_comment = comment
                self._advance()
                break

            # Empty line
            if not stripped:
                node.options.append(EmptyLine(line_number=self.current_line_num))
                self._advance()
                continue

            # Config or menuconfig entry within choice
            if stripped.startswith("config "):
                node.entries.append(self._parse_config_entry())
                continue

            if stripped.startswith("menuconfig "):
                node.entries.append(self._parse_menuconfig_entry())
                continue

            # Nested if block within choice
            if stripped.startswith("if "):
                node.entries.append(self._parse_if_block())
                continue

            # Comment
            if stripped.startswith("#"):
                text = stripped[1:].strip() if len(stripped) > 1 else ""
                node.options.append(
                    Comment(text=text, line_number=self.current_line_num)
                )
                self._advance()
                continue

            # Help block
            if stripped.startswith("help"):
                node.options.append(self._parse_help_block())
                continue

            # Choice option
            option = self._parse_config_option()
            if option:
                node.options.append(option)
            else:
                self._advance()

        return node

    def _parse_menu(self) -> MenuEntry:
        """Parse a menu block."""
        line = self._current_line()
        stripped = line.lstrip()

        # Extract title (remove quotes if present)
        title = stripped[5:].strip()
        if title.startswith('"') and title.endswith('"'):
            title = title[1:-1]

        node = MenuEntry(title=title, line_number=self.current_line_num)
        self._advance()

        # Parse until 'endmenu'
        while self.pos < len(self.lines):
            line = self._current_line()
            stripped = line.lstrip()

            if stripped.startswith("endmenu"):
                # Extract inline comment if present
                _, comment = self._extract_inline_comment(line)
                node.inline_comment = comment
                self._advance()
                break

            # Depends on for menu
            if stripped.startswith("depends on "):
                node.depends.append(stripped[11:].strip())
                self._advance()
                continue

            # Otherwise parse as statement
            stmt = self._parse_statement()
            if stmt:
                node.statements.append(stmt)

        return node

    def _parse_if_block(self) -> IfBlock:
        """Parse an if/endif block."""
        line = self._current_line()
        stripped = line.lstrip()

        condition = stripped[3:].strip()
        node = IfBlock(condition=condition, line_number=self.current_line_num)
        self._advance()

        # Parse until 'endif'
        while self.pos < len(self.lines):
            line = self._current_line()
            stripped = line.lstrip()

            if stripped.startswith("endif"):
                # Extract inline comment if present
                _, comment = self._extract_inline_comment(line)
                node.inline_comment = comment
                self._advance()
                break

            stmt = self._parse_statement()
            if stmt:
                node.statements.append(stmt)

        return node

    def _parse_source(self) -> SourceStatement:
        """Parse a source statement."""
        line = self._current_line()
        stripped = line.lstrip()

        for src_type in ["orsource", "osource", "rsource", "source"]:
            if stripped.startswith(src_type + " "):
                path = stripped[len(src_type) :].strip()
                if path.startswith('"') and path.endswith('"'):
                    path = path[1:-1]
                node = SourceStatement(
                    source_type=src_type, path=path, line_number=self.current_line_num
                )
                self._advance()
                return node

        # Shouldn't reach here
        self._advance()
        return SourceStatement(
            source_type="source", path="", line_number=self.current_line_num
        )

    def _parse_comment_statement(self) -> CommentStatement:
        """Parse a 'comment' statement."""
        line = self._current_line()
        stripped = line.lstrip()

        text = stripped[8:].strip()
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]

        node = CommentStatement(text=text, line_number=self.current_line_num)
        self._advance()

        # Check for depends on
        while self.pos < len(self.lines):
            line = self._current_line()
            stripped = line.lstrip()

            if not stripped or line[0] not in (" ", "\t"):
                break

            if stripped.startswith("depends on "):
                node.depends.append(stripped[11:].strip())
                self._advance()
            else:
                break

        return node


class KconfigFormatter:
    """Formatter for Kconfig AST."""

    def __init__(self, config: LinterConfig):
        self.config = config
        self.lines: list[str] = []

    def format(self, ast: list[ASTNode]) -> list[str]:
        """Format an AST into lines."""
        self.lines = []
        self._format_statements(ast, indent_level=0, in_config=False)

        # Ensure file ends with newline
        if self.lines and not self.lines[-1].endswith("\n"):
            self.lines[-1] += "\n"

        return self.lines

    def _get_indent(self, level: int, extra_level: int = 0) -> str:
        """Get indentation string."""
        total_level = level + extra_level

        if self.config.use_spaces:
            return " " * (total_level * self.config.primary_indent_spaces)
        else:
            return "\t" * total_level

    def _get_help_indent(self, level: int) -> str:
        """Get help text indentation."""
        if self.config.use_spaces:
            base = self.config.primary_indent_spaces
            if self.config.indent_sub_items:
                base += level * self.config.primary_indent_spaces
            return " " * (base + self.config.help_indent_spaces)
        else:
            base_tabs = 1
            if self.config.indent_sub_items:
                base_tabs += level
            return "\t" * base_tabs + " " * self.config.help_indent_spaces

    def _wrap_line(self, line: str, base_indent: str) -> list[str]:
        """Wrap a long line with continuation characters."""
        # Strip newline if present
        line = line.rstrip("\n")

        # Calculate continuation indent (base indent + one level)
        if self.config.use_spaces:
            cont_indent = base_indent + " " * self.config.primary_indent_spaces
        else:
            cont_indent = base_indent + "\t"

        # Split on && or ||
        if "&&" in line:
            separator = "&&"
        elif "||" in line:
            separator = "||"
        else:
            return [line]

        # Find the prefix (everything before the first condition)
        parts = line.split(separator)
        if not parts:
            return [line]

        # Start with the prefix
        result_lines = []
        current_line = parts[0].rstrip()

        for i, part in enumerate(parts[1:], 1):
            part = part.strip()
            test_line = f"{current_line} {separator} {part}"

            # If adding this part would exceed max length, wrap
            if len(test_line) > self.config.max_line_length:
                # End current line with backslash
                result_lines.append(current_line + " \\")
                # Start new line with continuation indent
                current_line = f"{cont_indent}{separator} {part}"
            else:
                current_line = test_line

        # Add the last line
        result_lines.append(current_line)

        return result_lines

    def _append_inline_comment(self, line: str, inline_comment: str) -> str:
        """Append inline comment to a line if present.

        Args:
            line: The line to append to
            inline_comment: The inline comment (with # prefix)

        Returns:
            Line with inline comment appended with proper spacing
        """
        if not inline_comment:
            return line

        # Ensure there are 2 spaces before the comment
        return f"{line}  {inline_comment}"

    def _format_statements(
        self, statements: list[ASTNode], indent_level: int, in_config: bool
    ):
        """Format a list of statements."""
        prev_was_empty = False
        prev_stmt_type = None

        for i, stmt in enumerate(statements):
            # Handle empty line consolidation
            if isinstance(stmt, EmptyLine):
                if self.config.consolidate_empty_lines:
                    if not prev_was_empty:
                        self.lines.append("")
                        prev_was_empty = True
                else:
                    self.lines.append("")
                    prev_was_empty = True
                continue

            # Insert blank line before certain statement types if not already present
            if not prev_was_empty and prev_stmt_type is not None:
                if self._should_insert_blank_line(prev_stmt_type, type(stmt).__name__):
                    self.lines.append("")

            prev_was_empty = False
            prev_stmt_type = type(stmt).__name__

            if isinstance(stmt, Comment):
                self._format_comment(stmt, indent_level, in_config)
            elif isinstance(stmt, ConfigEntry):
                self._format_config_entry(stmt, indent_level)
            elif isinstance(stmt, ChoiceEntry):
                self._format_choice(stmt, indent_level)
            elif isinstance(stmt, MenuEntry):
                self._format_menu(stmt, indent_level)
            elif isinstance(stmt, IfBlock):
                self._format_if_block(stmt, indent_level)
            elif isinstance(stmt, SourceStatement):
                self._format_source(stmt, indent_level)
            elif isinstance(stmt, CommentStatement):
                self._format_comment_statement(stmt, indent_level)
            elif isinstance(stmt, UnknownLine):
                self._format_unknown_line(stmt, indent_level, in_config)

    def _should_insert_blank_line(self, prev_type: str, current_type: str) -> bool:
        """Determine if a blank line should be inserted between two statement types.

        Args:
            prev_type: The type name of the previous statement
            current_type: The type name of the current statement

        Returns:
            True if a blank line should be inserted
        """
        # Statement types that should be separated by blank lines
        block_types = {
            "ConfigEntry",
            "ChoiceEntry",
            "MenuEntry",
            "IfBlock",
            "CommentStatement",
        }

        # Always separate blocks from each other
        if prev_type in block_types and current_type in block_types:
            return True

        return False

    def _format_comment(self, node: Comment, indent_level: int, in_config: bool):
        """Format a comment line."""
        indent = self._get_indent(indent_level, 1 if in_config else 0)

        # Ensure space after #
        if node.text:
            self.lines.append(f"{indent}# {node.text}")
        else:
            self.lines.append(f"{indent}#")

    def _format_config_entry(self, node: ConfigEntry, indent_level: int):
        """Format a config or menuconfig entry."""
        indent = self._get_indent(indent_level)
        line = f"{indent}{node.config_type} {node.name}"
        line = self._append_inline_comment(line, node.inline_comment)
        self.lines.append(line)

        # Format options with empty line consolidation
        prev_was_empty = False
        for option in node.options:
            if isinstance(option, EmptyLine):
                if self.config.consolidate_empty_lines:
                    if not prev_was_empty:
                        self.lines.append("")
                        prev_was_empty = True
                else:
                    self.lines.append("")
                    prev_was_empty = True
            else:
                prev_was_empty = False
                if isinstance(option, Comment):
                    self._format_comment(option, indent_level, in_config=True)
                elif isinstance(option, HelpText):
                    self._format_help_text(option, indent_level)
                elif isinstance(option, ConfigOption):
                    self._format_config_option(option, indent_level)
                elif isinstance(option, UnknownLine):
                    self._format_unknown_line(option, indent_level, in_config=True)

    def _format_config_option(self, node: ConfigOption, indent_level: int):
        """Format a config option."""
        indent = self._get_indent(indent_level, 1)

        # Build the line
        if node.option_type == "depends_on":
            line = f"{indent}depends on {node.value}"
        elif node.option_type in ["bool", "tristate", "string", "int", "hex"]:
            if node.value:
                line = f"{indent}{node.option_type} {node.value}"
            else:
                line = f"{indent}{node.option_type}"
        elif node.option_type in ["def_bool", "def_tristate"]:
            line = f"{indent}{node.option_type} {node.value}"
        else:
            line = f"{indent}{node.option_type.replace('_', ' ')} {node.value}"

        if node.condition:
            line += f" if {node.condition}"

        # Append inline comment before checking length
        line = self._append_inline_comment(line, node.inline_comment)

        # Check if line is too long and needs wrapping
        if len(line) > self.config.max_line_length and ("&&" in line or "||" in line):
            wrapped_lines = self._wrap_line(line, indent)
            self.lines.extend(wrapped_lines)
        else:
            self.lines.append(line)

    def _format_help_text(self, node: HelpText, indent_level: int):
        """Format help text block."""
        indent = self._get_indent(indent_level, 1)
        self.lines.append(f"{indent}help")

        help_indent = self._get_help_indent(indent_level)

        if self.config.reflow_help_text:
            # Reflow help text
            lines = self._reflow_help_text(node.lines, help_indent)
            self.lines.extend(lines)
        else:
            # Just apply indentation, consolidating consecutive blank lines
            prev_was_empty = False
            for line in node.lines:
                if line:
                    self.lines.append(f"{help_indent}{line}")
                    prev_was_empty = False
                else:
                    if not prev_was_empty:
                        self.lines.append("")
                        prev_was_empty = True

    def _reflow_help_text(self, text_lines: list[str], indent: str) -> list[str]:
        """Reflow help text to fit max line length."""
        # Calculate available width
        indent_width = len(indent.replace("\t", " " * 4))
        available_width = self.config.max_line_length - indent_width

        if available_width < 20:
            available_width = 40

        result = []

        # Split into paragraphs, consolidating consecutive blank lines
        paragraphs = []
        current_para = []
        prev_was_empty = False

        for line in text_lines:
            if not line:
                if current_para:
                    paragraphs.append(current_para)
                    current_para = []
                # Only add one empty paragraph for consecutive blank lines
                if not prev_was_empty:
                    paragraphs.append([])  # Empty paragraph
                    prev_was_empty = True
            else:
                current_para.append(line)
                prev_was_empty = False

        if current_para:
            paragraphs.append(current_para)

        # Reflow each paragraph using textwrap
        for para in paragraphs:
            if not para:
                result.append("")
                continue

            # Join paragraph into single text
            text = " ".join(para)

            if not text.strip():
                continue

            # Use textwrap.fill() to reflow the text
            wrapped = textwrap.fill(
                text,
                width=available_width,
                initial_indent="",
                subsequent_indent="",
                break_long_words=False,
                break_on_hyphens=False,
            )

            # Add indent to each line
            for line in wrapped.split("\n"):
                result.append(f"{indent}{line}")

        return result

    def _format_choice(self, node: ChoiceEntry, indent_level: int):
        """Format a choice block."""
        indent = self._get_indent(indent_level)

        if node.name:
            self.lines.append(f"{indent}choice {node.name}")
        else:
            self.lines.append(f"{indent}choice")

        # Format options
        for option in node.options:
            if isinstance(option, EmptyLine):
                # Skip empty lines in choice options - we'll add proper spacing
                continue
            elif isinstance(option, Comment):
                self._format_comment(option, indent_level, in_config=True)
            elif isinstance(option, HelpText):
                self._format_help_text(option, indent_level)
            elif isinstance(option, ConfigOption):
                self._format_config_option(option, indent_level)
            elif isinstance(option, UnknownLine):
                self._format_unknown_line(option, indent_level, in_config=True)

        # Format entries (config, menuconfig, if blocks, etc.)
        # Check if there are any non-empty-line options before entries
        has_real_options = any(not isinstance(opt, EmptyLine) for opt in node.options)

        for i, entry in enumerate(node.entries):
            # Add blank line before entries
            # - Always before the first one if there are real options
            # - Before subsequent ones (except for nested if blocks)
            if i > 0 or has_real_options:
                self.lines.append("")

            # Format based on entry type
            next_level = indent_level + (1 if self.config.indent_sub_items else 0)
            if isinstance(entry, ConfigEntry):
                self._format_config_entry(entry, next_level)
            elif isinstance(entry, IfBlock):
                self._format_if_block(entry, next_level)
            elif isinstance(entry, MenuEntry):
                self._format_menu(entry, next_level)
            elif isinstance(entry, ChoiceEntry):
                self._format_choice(entry, next_level)
            elif isinstance(entry, SourceStatement):
                self._format_source(entry, next_level)
            elif isinstance(entry, CommentStatement):
                self._format_comment_statement(entry, next_level)
            elif isinstance(entry, Comment):
                self._format_comment(entry, next_level, in_config=False)
            elif isinstance(entry, EmptyLine):
                self.lines.append("")
            elif isinstance(entry, UnknownLine):
                self._format_unknown_line(entry, next_level, in_config=False)

        # Add blank line before endchoice if there are entries
        if node.entries and self.lines and self.lines[-1] != "":
            self.lines.append("")

        # Format endchoice with inline comment
        if self.config.indent_sub_items:
            endchoice_line = f"{self._get_indent(indent_level, 1)}endchoice"
        else:
            endchoice_line = f"{indent}endchoice"
        endchoice_line = self._append_inline_comment(
            endchoice_line, node.inline_comment
        )
        self.lines.append(endchoice_line)

    def _format_menu(self, node: MenuEntry, indent_level: int):
        """Format a menu block."""
        indent = self._get_indent(indent_level)
        self.lines.append(f'{indent}menu "{node.title}"')

        # Depends
        option_indent = self._get_indent(indent_level, 1)
        for dep in node.depends:
            self.lines.append(f"{option_indent}depends on {dep}")

        # Statements
        next_level = indent_level + (1 if self.config.indent_sub_items else 0)
        self._format_statements(node.statements, next_level, in_config=False)

        # Add blank line before endmenu if there are statements
        if node.statements and self.lines and self.lines[-1] != "":
            self.lines.append("")

        if self.config.indent_sub_items:
            endmenu_line = f"{self._get_indent(indent_level)}endmenu"
        else:
            endmenu_line = f"{indent}endmenu"
        endmenu_line = self._append_inline_comment(endmenu_line, node.inline_comment)
        self.lines.append(endmenu_line)

    def _format_if_block(self, node: IfBlock, indent_level: int):
        """Format an if/endif block."""
        indent = self._get_indent(indent_level)
        line = f"{indent}if {node.condition}"

        # Check if line needs wrapping
        if len(line) > self.config.max_line_length and ("&&" in line or "||" in line):
            wrapped_lines = self._wrap_line(line, indent)
            self.lines.extend(wrapped_lines)
        else:
            self.lines.append(line)

        next_level = indent_level + (1 if self.config.indent_sub_items else 0)
        self._format_statements(node.statements, next_level, in_config=False)

        # Add blank line before endif if there are statements
        if node.statements and self.lines and self.lines[-1] != "":
            self.lines.append("")

        # Format endif with optional inline comment
        endif_indent = (
            self._get_indent(indent_level) if self.config.indent_sub_items else indent
        )
        endif_line = f"{endif_indent}endif"
        endif_line = self._append_inline_comment(endif_line, node.inline_comment)
        self.lines.append(endif_line)

    def _format_source(self, node: SourceStatement, indent_level: int):
        """Format a source statement."""
        indent = self._get_indent(indent_level)
        self.lines.append(f'{indent}{node.source_type} "{node.path}"')

    def _format_comment_statement(self, node: CommentStatement, indent_level: int):
        """Format a comment statement."""
        indent = self._get_indent(indent_level)
        self.lines.append(f'{indent}comment "{node.text}"')

        option_indent = self._get_indent(indent_level, 1)
        for dep in node.depends:
            self.lines.append(f"{option_indent}depends on {dep}")

    def _format_unknown_line(
        self, node: UnknownLine, indent_level: int, in_config: bool
    ):
        """Format an unknown line - preserve original indentation or apply config indent."""
        # Get original line without newline and strip existing indentation
        text = node.text.rstrip("\n\r").lstrip()

        # If we're in a config, indent it like an option
        if in_config and text:
            indent = self._get_indent(indent_level, 1)
            self.lines.append(f"{indent}{text}")
        else:
            # At top level, preserve stripped content
            self.lines.append(text)


class KconfigLinter:
    """Linter for Kconfig files."""

    def __init__(self, config: LinterConfig):
        self.config = config
        self.issues: list[LintIssue] = []
        self.parser = KconfigParser()
        self.formatter = KconfigFormatter(config)

    def lint_file(self, filepath: Path) -> list[LintIssue]:
        """Lint a Kconfig file and return list of issues."""
        self.issues = []

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                lines = content.splitlines(keepends=True)
        except Exception as e:
            self.issues.append(LintIssue(0, None, "error", f"Failed to read file: {e}"))
            return self.issues

        # Check each line for basic issues
        empty_line_count = 0
        for i, line in enumerate(lines, 1):
            line_no_newline = line.rstrip("\n\r")

            # Trailing whitespace
            if line_no_newline != line_no_newline.rstrip():
                self.issues.append(
                    LintIssue(
                        i,
                        len(line_no_newline.rstrip()) + 1,
                        "error",
                        "Trailing whitespace not allowed",
                    )
                )

            # Line length
            if len(line_no_newline) > self.config.max_line_length:
                self.issues.append(
                    LintIssue(
                        i,
                        self.config.max_line_length + 1,
                        "error",
                        f"Line exceeds {self.config.max_line_length} characters",
                    )
                )

            # Multiple consecutive empty lines
            if not line.strip():
                empty_line_count += 1
                if self.config.consolidate_empty_lines and empty_line_count > 1:
                    self.issues.append(
                        LintIssue(
                            i,
                            1,
                            "warning",
                            "Multiple consecutive empty lines (should be consolidated to one)",
                        )
                    )
            else:
                empty_line_count = 0

            # Comment spacing
            stripped = line_no_newline.lstrip()
            if stripped.startswith("#") and len(stripped) > 1 and stripped[1] != " ":
                indent_len = len(line_no_newline) - len(stripped)
                self.issues.append(
                    LintIssue(
                        i,
                        indent_len + 2,
                        "warning",
                        'Comments should have a space after # (use "# Comment" not "#Comment")',
                    )
                )

        # Check indentation issues (pass 2 - needs context)
        in_help_block = False
        for i, line in enumerate(lines, 1):
            line_no_newline = line.rstrip("\n\r")
            if not line_no_newline.strip():
                continue

            stripped = line_no_newline.lstrip()
            indent = line_no_newline[: len(line_no_newline) - len(stripped)]

            # Track help blocks for special indentation handling
            if stripped.startswith("help"):
                in_help_block = True
                continue
            elif in_help_block:
                # Check if we're still in help text
                # Help text can have tab + spaces (that's the expected format)
                if stripped.startswith(
                    (
                        "#",
                        "config",
                        "menuconfig",
                        "choice",
                        "menu",
                        "if ",
                        "endif",
                        "endmenu",
                        "endchoice",
                        "source",
                        "rsource",
                        "comment ",
                        "mainmenu",
                    )
                ):
                    # We've hit a keyword, exit help block
                    in_help_block = False
                else:
                    # Still in help text - validate help text indentation
                    if not self.config.use_spaces and stripped:
                        # This is help text content - should be tab + spaces
                        expected_prefix = "\t" + " " * self.config.help_indent_spaces
                        if not line_no_newline.startswith(expected_prefix):
                            # Check if it's just a tab (wrong)
                            if line_no_newline.startswith(
                                "\t"
                            ) and not line_no_newline.startswith(expected_prefix):
                                self.issues.append(
                                    LintIssue(
                                        i,
                                        1,
                                        "error",
                                        f"Help text should be indented with tab + {self.config.help_indent_spaces} spaces",
                                    )
                                )
                    continue

            # Check for mixed tabs and spaces (but not in help text)
            if "\t" in indent and " " in indent:
                self.issues.append(
                    LintIssue(
                        i,
                        1,
                        "error",
                        "Mixed tabs and spaces in indentation",
                    )
                )

            # Check tabs vs spaces based on config
            if indent:
                if self.config.use_spaces:
                    if "\t" in indent:
                        self.issues.append(
                            LintIssue(
                                i,
                                1,
                                "error",
                                "Use spaces for indentation (tabs not allowed)",
                            )
                        )
                    # Check if indentation is multiple of configured spaces
                    elif len(indent) % self.config.primary_indent_spaces != 0:
                        self.issues.append(
                            LintIssue(
                                i,
                                1,
                                "error",
                                f"Indentation should be a multiple of {self.config.primary_indent_spaces} spaces",
                            )
                        )
                else:
                    # Using tabs
                    if " " in indent:
                        self.issues.append(
                            LintIssue(
                                i,
                                1,
                                "error",
                                "Use tabs for indentation (spaces not allowed except in help text)",
                            )
                        )

        # Parse and check AST-level rules
        ast = self.parser.parse(content)
        self._lint_ast(ast, filepath)

        return self.issues

    def _lint_ast(self, nodes: list[ASTNode], filepath: Path):
        """Lint AST nodes for structural issues."""
        for node in nodes:
            if isinstance(node, ConfigEntry):
                self._lint_config_entry(node)
            elif isinstance(node, ChoiceEntry):
                self._lint_choice(node)
            elif isinstance(node, MenuEntry):
                self._lint_menu(node)
            elif isinstance(node, IfBlock):
                self._lint_if_block(node)

    def _lint_config_entry(self, node: ConfigEntry):
        """Lint a config entry."""
        # Check config name
        if len(node.name) > self.config.max_option_name_length:
            self.issues.append(
                LintIssue(
                    node.line_number,
                    len(node.config_type) + 2,
                    "error",
                    f"Config name exceeds {self.config.max_option_name_length} characters",
                )
            )

        # Check uppercase if configured
        if self.config.enforce_uppercase_configs:
            if node.name != node.name.upper():
                self.issues.append(
                    LintIssue(
                        node.line_number,
                        len(node.config_type) + 2,
                        "error",
                        "Config option name must be uppercase",
                    )
                )

        # Check prefix length
        if self.config.min_prefix_length > 0 and "_" in node.name:
            prefix = node.name.split("_")[0]
            if len(prefix) < self.config.min_prefix_length:
                self.issues.append(
                    LintIssue(
                        node.line_number,
                        len(node.config_type) + 2,
                        "warning",
                        f"Config prefix should be at least {self.config.min_prefix_length} characters",
                    )
                )

    def _lint_choice(self, node: ChoiceEntry):
        """Lint a choice block."""
        self._lint_ast(node.entries, None)

    def _lint_menu(self, node: MenuEntry):
        """Lint a menu block."""
        self._lint_ast(node.statements, None)

    def _lint_if_block(self, node: IfBlock):
        """Lint an if block."""
        self._lint_ast(node.statements, None)

    # Compatibility methods for tests
    def _get_line_type(self, line: str) -> str:
        """Determine the type of Kconfig line (for test compatibility)."""
        stripped = line.lstrip()

        if stripped.startswith("#"):
            return "comment_line"
        elif stripped.startswith("config "):
            return "config"
        elif stripped.startswith("menuconfig "):
            return "menuconfig"
        elif stripped.startswith("menu "):
            return "menu"
        elif stripped.startswith("endmenu"):
            return "endmenu"
        elif stripped.startswith("choice"):
            return "choice"
        elif stripped.startswith("endchoice"):
            return "endchoice"
        elif stripped.startswith("if "):
            return "if"
        elif stripped.startswith("endif"):
            return "endif"
        elif stripped.startswith(("source ", "rsource ")):
            return "source"
        elif stripped.startswith("comment "):
            return "comment"
        elif stripped.startswith("help"):
            return "help"
        elif re.match(
            r"^\s*(bool|tristate|string|int|hex|def_bool|def_tristate|prompt|default|depends on|select|imply|range|option)\s",
            stripped,
        ):
            return "option"
        else:
            return "other"

    def _check_config_name(self, line: str, line_num: int):
        """Check config/menuconfig name formatting (for test compatibility)."""
        match = re.match(r"^\s*(config|menuconfig)\s+(\S+)", line)
        if not match:
            return

        config_name = match.group(2)

        if len(config_name) > self.config.max_option_name_length:
            self.issues.append(
                LintIssue(
                    line_num,
                    match.start(2) + 1,
                    "error",
                    f"Config name exceeds {self.config.max_option_name_length} characters",
                )
            )

        if self.config.enforce_uppercase_configs:
            if config_name != config_name.upper():
                self.issues.append(
                    LintIssue(
                        line_num,
                        match.start(2) + 1,
                        "error",
                        "Config option name must be uppercase",
                    )
                )

        if self.config.min_prefix_length > 0 and "_" in config_name:
            prefix = config_name.split("_")[0]
            if len(prefix) < self.config.min_prefix_length:
                self.issues.append(
                    LintIssue(
                        line_num,
                        match.start(2) + 1,
                        "warning",
                        f"Config prefix should be at least {self.config.min_prefix_length} characters",
                    )
                )

    def format_file(self, filepath: Path) -> tuple[list[str], list[LintIssue]]:
        """Format a Kconfig file and return the formatted lines."""
        self.issues = []

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            self.issues.append(LintIssue(0, None, "error", f"Failed to read file: {e}"))
            return [], self.issues

        ast = self.parser.parse(content)
        formatted_lines = self.formatter.format(ast)

        # Add newlines
        result = [
            line + "\n" if not line.endswith("\n") else line for line in formatted_lines
        ]

        return result, self.issues


def _dump_ast(nodes: list[ASTNode], indent: int = 0):
    """Dump AST structure for debugging."""
    prefix = "  " * indent

    for node in nodes:
        if isinstance(node, EmptyLine):
            print(f"{prefix}EmptyLine")
        elif isinstance(node, Comment):
            print(f"{prefix}Comment: {node.text!r}")
        elif isinstance(node, ConfigEntry):
            print(f"{prefix}ConfigEntry: {node.config_type} {node.name}")
            if node.options:
                print(f"{prefix}  options:")
                _dump_ast(node.options, indent + 2)
        elif isinstance(node, ConfigOption):
            cond_str = f" if {node.condition}" if node.condition else ""
            print(f"{prefix}ConfigOption: {node.option_type} {node.value!r}{cond_str}")
        elif isinstance(node, HelpText):
            print(f"{prefix}HelpText: {len(node.lines)} line(s)")
            for line in node.lines:
                print(f"{prefix}  {line!r}")
        elif isinstance(node, ChoiceEntry):
            name_str = f" ({node.name})" if node.name else ""
            print(f"{prefix}ChoiceEntry{name_str}")
            if node.options:
                print(f"{prefix}  options:")
                _dump_ast(node.options, indent + 2)
            if node.entries:
                print(f"{prefix}  entries:")
                _dump_ast(node.entries, indent + 2)
        elif isinstance(node, MenuEntry):
            print(f"{prefix}MenuEntry: {node.title!r}")
            if node.depends:
                print(f"{prefix}  depends: {node.depends}")
            if node.statements:
                print(f"{prefix}  statements:")
                _dump_ast(node.statements, indent + 2)
        elif isinstance(node, IfBlock):
            print(f"{prefix}IfBlock: {node.condition}")
            if node.statements:
                print(f"{prefix}  statements:")
                _dump_ast(node.statements, indent + 2)
        elif isinstance(node, SourceStatement):
            print(f"{prefix}SourceStatement: {node.source_type} {node.path!r}")
        elif isinstance(node, CommentStatement):
            print(f"{prefix}CommentStatement: {node.text!r}")
            if node.depends:
                print(f"{prefix}  depends: {node.depends}")
        elif isinstance(node, UnknownLine):
            print(f"{prefix}UnknownLine: {node.text!r}")
        else:
            print(f"{prefix}{type(node).__name__}")


def main():
    """Main entry point for the linter."""
    parser = argparse.ArgumentParser(
        description="Lint and format Kconfig files for style compliance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Style Presets:
  zephyr   - Zephyr style (100 cols, tabs, help at tab+2 spaces)
  espidf   - ESP-IDF style (120 cols, 4-space indent, hierarchical, uppercase configs)

Examples:
  # Lint with Zephyr preset
  kconfigstyle Kconfig

  # Format file in-place with ESP-IDF preset
  kconfigstyle --write --preset espidf Kconfig

  # Custom: spaces instead of tabs, 120 char lines
  kconfigstyle --use-spaces --max-line-length 120 --write Kconfig
        """,
    )

    parser.add_argument(
        "files", nargs="+", type=Path, help="Kconfig files to lint/format"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--preset",
        choices=["zephyr", "espidf"],
        help="Use a style preset (individual options override preset values)",
    )
    parser.add_argument(
        "--write",
        "-w",
        action="store_true",
        help="Write formatted output back to files (format mode)",
    )
    parser.add_argument(
        "--use-spaces",
        action="store_true",
        help="Use spaces instead of tabs for indentation",
    )
    parser.add_argument(
        "--primary-indent",
        type=int,
        help="Number of spaces for primary indentation (default: 4)",
    )
    parser.add_argument(
        "--help-indent",
        type=int,
        help="Number of extra spaces for help text indentation (default: 2)",
    )
    parser.add_argument(
        "--max-line-length",
        type=int,
        help="Maximum line length (default: 100 for Zephyr, 120 for ESP-IDF)",
    )
    parser.add_argument(
        "--max-option-length",
        type=int,
        help="Maximum config option name length (default: 50)",
    )
    parser.add_argument(
        "--uppercase-configs",
        action="store_true",
        help="Require config names to be uppercase",
    )
    parser.add_argument(
        "--min-prefix-length",
        type=int,
        help="Minimum prefix length for config names (default: 3 for ESP-IDF)",
    )
    parser.add_argument(
        "--indent-sub-items",
        action="store_true",
        help="Use hierarchical indentation for sub-items (ESP-IDF style)",
    )
    parser.add_argument(
        "--consolidate-empty-lines",
        action="store_true",
        help="Consolidate multiple consecutive empty lines into one",
    )
    parser.add_argument(
        "--reflow-help",
        action="store_true",
        help="Reflow help text to fit within max line length",
    )
    parser.add_argument("--verbose", action="store_true", help="Show detailed output")
    parser.add_argument(
        "--dump-ast",
        action="store_true",
        help="Dump the parsed AST structure instead of linting/formatting",
    )
    parser.add_argument(
        "--print-formatted",
        action="store_true",
        help="Print formatted output to stdout instead of linting (for debugging)",
    )

    args = parser.parse_args()

    # Start with preset or default
    if args.preset == "espidf":
        config = LinterConfig.espidf_preset()
    elif args.preset == "zephyr":
        config = LinterConfig.zephyr_preset()
    else:
        config = LinterConfig.zephyr_preset()

    # Override with command-line arguments
    if args.use_spaces:
        config.use_spaces = True
    if args.primary_indent is not None:
        config.primary_indent_spaces = args.primary_indent
    if args.help_indent is not None:
        config.help_indent_spaces = args.help_indent
    if args.max_line_length is not None:
        config.max_line_length = args.max_line_length
    if args.max_option_length is not None:
        config.max_option_name_length = args.max_option_length
    if args.uppercase_configs:
        config.enforce_uppercase_configs = True
    if args.min_prefix_length is not None:
        config.min_prefix_length = args.min_prefix_length
    if args.indent_sub_items:
        config.indent_sub_items = True
    if args.consolidate_empty_lines:
        config.consolidate_empty_lines = True
    if args.reflow_help:
        config.reflow_help_text = True

    linter = KconfigLinter(config)
    total_issues = 0
    files_with_issues = 0
    files_formatted = 0

    # Process each file
    for filepath in args.files:
        if not filepath.exists():
            print(f"Error: File not found: {filepath}", file=sys.stderr)
            continue

        if args.dump_ast:
            # AST dump mode
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                ast = linter.parser.parse(content)
                print(f"\n{'=' * 60}")
                print(f"AST for {filepath}")
                print(f"{'=' * 60}")
                _dump_ast(ast, indent=0)
            except Exception as e:
                print(f"Error parsing {filepath}: {e}", file=sys.stderr)
            exit(0)

        if args.print_formatted:
            # Print formatted output mode (for debugging)
            try:
                formatted_lines, issues = linter.format_file(filepath)

                print(f"\n{'=' * 60}")
                print(f"Formatted output for {filepath}")
                print(f"{'=' * 60}")
                for line in formatted_lines:
                    print(line, end="")

                if issues:
                    print(f"\n\n{'=' * 60}")
                    print("Unfixable issues:")
                    print(f"{'=' * 60}")
                    for issue in sorted(issues, key=lambda x: x.line_number):
                        print(f"  {issue}")
            except Exception as e:
                print(f"Error formatting {filepath}: {e}", file=sys.stderr)
                import traceback

                traceback.print_exc()
            continue

        if args.write:
            # Format mode
            if args.verbose:
                print(f"\nFormatting {filepath}...")

            formatted_lines, issues = linter.format_file(filepath)

            # Write back to file
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.writelines(formatted_lines)
                files_formatted += 1
                if args.verbose:
                    print("  ✓ Formatted")

                if issues:
                    print(f"\n{filepath} (unfixable issues):")
                    for issue in sorted(issues, key=lambda x: x.line_number):
                        print(f"  {issue}")
                    total_issues += len(issues)
            except Exception as e:
                print(f"Error writing {filepath}: {e}", file=sys.stderr)
        else:
            # Lint mode
            if args.verbose:
                print(f"\nLinting {filepath}...")

            issues = linter.lint_file(filepath)

            if issues:
                files_with_issues += 1
                total_issues += len(issues)
                print(f"\n{filepath}:")
                for issue in sorted(issues, key=lambda x: x.line_number):
                    print(f"  {issue}")

    # Summary
    print(f"\n{'=' * 60}")
    if args.write:
        print(f"Formatted {files_formatted} file(s)")
        if total_issues > 0:
            print(f"Warning: {total_issues} unfixable issue(s) remain")
    else:
        print(f"Total: {total_issues} issue(s) in {files_with_issues} file(s)")

    return 1 if (not args.write and total_issues > 0) else 0


if __name__ == "__main__":
    sys.exit(main())
