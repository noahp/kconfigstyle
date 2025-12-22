#!/usr/bin/env python3
"""
Kconfig file linter and formatter with support for Zephyr and ESP-IDF styles.
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

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
            help_indent_spaces=4,  # ESP-IDF uses consistent 4-space indentation
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


class KconfigLinter:
    """Linter for Kconfig files."""

    def __init__(self, config: LinterConfig):
        self.config = config
        self.issues: list[LintIssue] = []

    def lint_file(self, filepath: Path) -> list[LintIssue]:
        """Lint a Kconfig file and return list of issues."""
        self.issues = []

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            self.issues.append(LintIssue(0, None, "error", f"Failed to read file: {e}"))
            return self.issues

        self._lint_lines(lines)
        return self.issues

    def format_file(self, filepath: Path) -> tuple[list[str], list[LintIssue]]:
        """Format a Kconfig file and return the formatted lines and any unfixable issues."""
        self.issues = []

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            self.issues.append(LintIssue(0, None, "error", f"Failed to read file: {e}"))
            return [], self.issues

        formatted_lines = self._format_lines(lines)
        return formatted_lines, self.issues

    def _format_lines(self, lines: list[str]) -> list[str]:
        """Format Kconfig lines according to configuration."""
        formatted = []
        in_help = False
        in_config_block = False  # Track if we're inside a config/menuconfig block
        indent_level = 0
        prev_was_empty = False
        help_lines = []  # Collect help text lines for reflow

        # First pass: join continuation lines
        joined_lines = self._join_continuation_lines(lines)

        for line in joined_lines:
            line_no_newline = line.rstrip("\n\r")

            # Skip if empty
            if not line.strip():
                # Empty lines within help text are allowed (don't terminate help block)
                # Help text can contain blank lines followed by more indented text
                # The help block only ends when we see a non-indented line after a blank

                # If in help and reflow is enabled, treat blank line as paragraph separator
                if in_help and self.config.reflow_help_text and help_lines:
                    formatted.extend(self._reflow_help_text(help_lines, indent_level))
                    help_lines = []
                    # Don't set in_help = False here! Keep it active.

                # Consolidate empty lines if configured
                if self.config.consolidate_empty_lines:
                    if not prev_was_empty:
                        formatted.append("")
                        prev_was_empty = True
                else:
                    formatted.append("")
                    prev_was_empty = True
                continue

            # Current line is not empty
            # Store prev_was_empty before we reset it
            had_empty_before = prev_was_empty
            prev_was_empty = False
            stripped = line_no_newline.lstrip()

            # Get line type, but if we're in help, check indentation to determine
            # if we're still in the help block
            if in_help:
                # Calculate expected help text indentation
                if self.config.use_spaces:
                    base_indent = self.config.primary_indent_spaces
                    if self.config.indent_sub_items:
                        base_indent += indent_level * self.config.primary_indent_spaces
                    expected_help_indent = " " * (
                        base_indent + self.config.help_indent_spaces
                    )
                else:
                    base_tabs = 1
                    if self.config.indent_sub_items:
                        base_tabs += indent_level
                    expected_help_indent = (
                        "\t" * base_tabs + " " * self.config.help_indent_spaces
                    )

                # Check if line starts with expected help indentation
                if line_no_newline.startswith(expected_help_indent):
                    # Line has proper help indentation - continue help block
                    # (even if it looks like a keyword)
                    line_type = "help_text"
                else:
                    # Indentation doesn't match expected help indent
                    potential_line_type = self._get_line_type(line_no_newline)

                    # Check if this is a keyword - keywords end help blocks
                    # when they don't have help text indentation
                    if potential_line_type in [
                        "config",
                        "menuconfig",
                        "choice",
                        "endchoice",
                        "menu",
                        "endmenu",
                        "if",
                        "endif",
                        "source",
                        "rsource",
                        "comment",
                    ]:
                        # Keyword without help indentation ends help block
                        if self.config.reflow_help_text and help_lines:
                            formatted.extend(
                                self._reflow_help_text(help_lines, indent_level)
                            )
                            help_lines = []
                        in_help = False
                        line_type = potential_line_type
                        # End config block for certain keywords
                        if line_type in [
                            "config",
                            "menuconfig",
                            "menu",
                            "if",
                            "endif",
                            "comment",
                        ]:
                            in_config_block = False
                    elif had_empty_before:
                        # Blank line before and indentation doesn't match - end help
                        if self.config.reflow_help_text and help_lines:
                            formatted.extend(
                                self._reflow_help_text(help_lines, indent_level)
                            )
                            help_lines = []
                        in_help = False
                        line_type = potential_line_type
                        # End config block for certain line types
                        if line_type in ["comment_line"]:
                            in_config_block = False
                    else:
                        # No blank before - treat as help text even if indentation is wrong
                        # (formatter will fix it)
                        line_type = "help_text"
            else:
                # Not in help block - determine line type normally
                line_type = self._get_line_type(
                    line_no_newline
                )  # Update indent level (for end markers, do it before formatting)
            if line_type in ["endmenu", "endif", "endchoice"] and indent_level > 0:
                indent_level -= 1

            # Check if we're entering or leaving a config block (BEFORE formatting)
            if line_type in ["config", "menuconfig"]:
                in_config_block = True
            elif line_type in [
                "menu",
                "endmenu",
                "choice",
                "endchoice",
                "if",
                "endif",
                "source",
            ]:
                in_config_block = False

            # Unindented lines that aren't recognized keywords also end config blocks
            # But comments don't end config blocks (they can appear anywhere)
            if (
                in_config_block
                and not line_no_newline.startswith((" ", "\t"))
                and line_type
                not in [
                    "config",
                    "menuconfig",
                    "option",
                    "help",
                    "help_text",
                    "comment_line",
                ]
            ):
                in_config_block = False

            # If we're in help and reflow is enabled, collect the text
            if in_help and self.config.reflow_help_text and line_type == "help_text":
                help_lines.append(stripped)
                # Don't format yet, we'll reflow later
            else:
                # Format the line normally
                formatted_line = self._format_line(
                    stripped, line_type, indent_level, in_help, in_config_block
                )

                # Check if this line should be wrapped with continuations
                if (
                    line_type in ["option", "if"]
                    and len(formatted_line) > self.config.max_line_length
                ):
                    # Get the base indent for this line
                    indent_str = formatted_line[
                        : len(formatted_line) - len(formatted_line.lstrip())
                    ]
                    wrapped = self._wrap_continuation_line(
                        formatted_line, indent_str, line_type
                    )
                    formatted.extend(wrapped)
                else:
                    formatted.append(formatted_line)

            # Update help state AFTER formatting (for help keyword)
            if line_type == "help":
                in_help = True

            # Update indent level for next iteration (for start markers)
            if line_type in ["menu", "if", "choice"]:
                indent_level += 1
        # Flush any remaining help text
        if self.config.reflow_help_text and help_lines:
            formatted.extend(self._reflow_help_text(help_lines, indent_level))

        # Ensure file ends with newline
        result = [
            line + "\n" if line or i < len(formatted) - 1 else line
            for i, line in enumerate(formatted)
        ]
        return result

    def _join_continuation_lines(self, lines: list[str]) -> list[str]:
        """Join lines that end with backslash continuation.

        Args:
            lines: Original lines from file

        Returns:
            List of lines with continuations joined
        """
        result = []
        i = 0

        while i < len(lines):
            line = lines[i].rstrip("\n\r")

            # Check if this line ends with backslash
            if line.rstrip().endswith("\\"):
                # Collect all continuation lines
                joined = line.rstrip()[:-1].rstrip()  # Remove \ and trailing space
                i += 1

                # Keep joining while we have continuations
                while i < len(lines):
                    next_line = lines[i].rstrip("\n\r")
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

                result.append(joined + "\n")
            else:
                result.append(line + "\n")
                i += 1

        return result

    def _format_line(
        self,
        stripped: str,
        line_type: str,
        indent_level: int,
        in_help: bool,
        in_config_block: bool = False,
    ) -> str:
        """Format a single line with proper indentation.

        Returns a single line string, which may need to be split into multiple
        lines if it's too long and supports continuation.
        """
        # Determine indentation
        if line_type == "help_text" or (in_help and not stripped.startswith("help")):
            # Help text indentation
            if self.config.use_spaces:
                base_indent = self.config.primary_indent_spaces
                if self.config.indent_sub_items:
                    base_indent += indent_level * self.config.primary_indent_spaces
                indent = " " * (base_indent + self.config.help_indent_spaces)
            else:
                base_tabs = 1
                if self.config.indent_sub_items:
                    base_tabs += indent_level
                indent = "\t" * base_tabs + " " * self.config.help_indent_spaces
        elif line_type in [
            "config",
            "menuconfig",
            "choice",
            "menu",
            "comment",
            "source",
            "if",
        ]:
            # Top-level declarations
            if self.config.indent_sub_items and indent_level > 0:
                if self.config.use_spaces:
                    indent = " " * (indent_level * self.config.primary_indent_spaces)
                else:
                    indent = "\t" * indent_level
            else:
                indent = ""
        elif line_type == "comment_line":
            # Comment lines should match the indentation level of their context
            # If inside a config block, indent like options
            if in_config_block:
                # Inside a config/menuconfig, indent like options
                base_level = 1
                if self.config.indent_sub_items:
                    base_level += indent_level
                if self.config.use_spaces:
                    indent = " " * (base_level * self.config.primary_indent_spaces)
                else:
                    indent = "\t" * base_level
            elif self.config.indent_sub_items and indent_level > 0:
                # Outside config blocks but inside menu/if, use hierarchical indent
                if self.config.use_spaces:
                    indent = " " * (indent_level * self.config.primary_indent_spaces)
                else:
                    indent = "\t" * indent_level
            else:
                indent = ""
        elif line_type in ["endmenu", "endif", "endchoice"]:
            # End markers
            if self.config.indent_sub_items and indent_level > 0:
                if self.config.use_spaces:
                    indent = " " * (indent_level * self.config.primary_indent_spaces)
                else:
                    indent = "\t" * indent_level
            else:
                indent = ""
        elif line_type in ["option", "help"] and not in_help:
            # Options indented one level
            base_level = 1
            if self.config.indent_sub_items:
                base_level += indent_level
            if self.config.use_spaces:
                indent = " " * (base_level * self.config.primary_indent_spaces)
            else:
                indent = "\t" * base_level
        elif line_type == "other" and not in_help and in_config_block:
            # "Other" lines inside config blocks get indented
            base_level = 1
            if self.config.indent_sub_items:
                base_level += indent_level
            if self.config.use_spaces:
                indent = " " * (base_level * self.config.primary_indent_spaces)
            else:
                indent = "\t" * base_level
        else:
            indent = ""

        # Fix comment spacing
        if stripped.startswith("#") and len(stripped) > 1 and stripped[1] != " ":
            stripped = "# " + stripped[1:]

        # Remove trailing whitespace
        result = (indent + stripped).rstrip()
        return result

    def _wrap_continuation_line(
        self, line: str, indent: str, line_type: str
    ) -> list[str]:
        """Wrap a long line using backslash continuation.

        Args:
            line: The full line including indentation
            indent: The base indentation for this line
            line_type: Type of line (option, if, etc.)

        Returns:
            List of lines with continuation backslashes
        """
        # If line is short enough, return as-is
        if len(line) <= self.config.max_line_length:
            return [line]

        # Strip the base indent to work with content
        if not line.startswith(indent):
            return [line]  # Can't process if indent doesn't match

        content = line[len(indent) :]

        # Determine what kind of wrapping we can do
        # For "depends on", "select", "default", etc., we can break at && or ||
        if line_type == "option":
            # Check for logical operators
            if " && " in content or " || " in content:
                return self._wrap_at_logical_operators(content, indent)

        # For "if" statements, similar logic
        if line_type == "if":
            if " && " in content or " || " in content:
                return self._wrap_at_logical_operators(content, indent)

        # If no special wrapping applies, return as-is
        return [line]

    def _wrap_at_logical_operators(self, content: str, base_indent: str) -> list[str]:
        """Wrap a line at logical operators (&& or ||).

        Args:
            content: The line content without base indentation
            base_indent: The indentation string to use for first line

        Returns:
            List of wrapped lines with backslash continuations
        """
        # Calculate continuation indent (base + one more level)
        if self.config.use_spaces:
            cont_indent = base_indent + " " * self.config.primary_indent_spaces
        else:
            cont_indent = base_indent + "\t"

        # Split by logical operators while preserving them
        import re

        # Split but keep the operators
        parts = re.split(r"(\s+(?:&&|\|\|)\s+)", content)

        lines = []
        current_line = base_indent + parts[0]

        for i in range(1, len(parts), 2):
            if i + 1 >= len(parts):
                break

            operator = parts[i].strip()
            next_part = parts[i + 1]

            # Try to add operator and next part to current line
            test_line = f"{current_line} {operator} {next_part}"

            # Check if it fits (accounting for the " \" at the end)
            if len(test_line) + 2 <= self.config.max_line_length:
                current_line = test_line
            else:
                # Flush current line with backslash
                lines.append(current_line.rstrip() + " \\")
                current_line = f"{cont_indent}{operator} {next_part}"

        # Add the last line (no backslash)
        lines.append(current_line.rstrip())

        return lines

    def _reflow_help_text(self, help_lines: list[str], indent_level: int) -> list[str]:
        """Reflow help text to fit within max line length.

        Args:
            help_lines: List of help text lines (already stripped of indentation)
            indent_level: Current hierarchical indent level

        Returns:
            List of formatted help text lines with proper indentation
        """
        # Calculate the indent for help text
        if self.config.use_spaces:
            base_indent = self.config.primary_indent_spaces
            if self.config.indent_sub_items:
                base_indent += indent_level * self.config.primary_indent_spaces
            indent_str = " " * (base_indent + self.config.help_indent_spaces)
        else:
            base_tabs = 1
            if self.config.indent_sub_items:
                base_tabs += indent_level
            indent_str = "\t" * base_tabs + " " * self.config.help_indent_spaces

        # Calculate available width for text
        indent_width = len(
            indent_str.replace("\t", " " * 4)
        )  # Assume tab = 4 spaces for width calc
        available_width = self.config.max_line_length - indent_width

        if available_width < 20:  # Sanity check
            available_width = 40

        formatted = []

        # Process help text in paragraphs (separated by empty lines)
        paragraphs = []
        current_paragraph = []

        for line in help_lines:
            if not line:  # Empty line = paragraph break
                if current_paragraph:
                    paragraphs.append(current_paragraph)
                    current_paragraph = []
                paragraphs.append([])  # Preserve empty line
            else:
                current_paragraph.append(line)

        if current_paragraph:
            paragraphs.append(current_paragraph)

        # Reflow each paragraph
        for paragraph in paragraphs:
            if not paragraph:  # Empty paragraph (was an empty line)
                formatted.append("")
                continue

            # Join paragraph into single text
            text = " ".join(paragraph)

            # Split into words and reflow
            words = text.split()
            if not words:
                continue

            current_line = words[0]
            for word in words[1:]:
                # Check if adding this word would exceed the line length
                if len(current_line) + 1 + len(word) <= available_width:
                    current_line += " " + word
                else:
                    # Flush current line and start new one
                    formatted.append(indent_str + current_line)
                    current_line = word

            # Add the last line
            if current_line:
                formatted.append(indent_str + current_line)

        return formatted

    def _lint_lines(self, lines: list[str]):
        """Perform linting on the lines of a Kconfig file."""
        in_help = False
        indent_level = 0
        empty_line_count = 0
        prev_was_empty = False

        for i, line in enumerate(lines, start=1):
            line_no_newline = line.rstrip("\n\r")

            # Check for trailing spaces
            if line_no_newline != line_no_newline.rstrip():
                self.issues.append(
                    LintIssue(
                        i,
                        len(line_no_newline.rstrip()) + 1,
                        "error",
                        "Trailing whitespace not allowed",
                    )
                )

            # Check for multiple consecutive empty lines
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
                prev_was_empty = True
            else:
                empty_line_count = 0

            # Check line length
            if len(line_no_newline) > self.config.max_line_length:
                self.issues.append(
                    LintIssue(
                        i,
                        self.config.max_line_length + 1,
                        "error",
                        f"Line exceeds {self.config.max_line_length} characters",
                    )
                )

            # Skip empty lines
            if not line.strip():
                continue

            # Store and reset empty line flag
            had_empty_before = prev_was_empty
            prev_was_empty = False

            # Detect line type - use same logic as _format_lines for help blocks
            if in_help:
                # Calculate expected help text indentation
                if self.config.use_spaces:
                    base_indent = self.config.primary_indent_spaces
                    if self.config.indent_sub_items:
                        base_indent += indent_level * self.config.primary_indent_spaces
                    expected_help_indent = " " * (
                        base_indent + self.config.help_indent_spaces
                    )
                else:
                    base_tabs = 1
                    if self.config.indent_sub_items:
                        base_tabs += indent_level
                    expected_help_indent = (
                        "\t" * base_tabs + " " * self.config.help_indent_spaces
                    )

                # Check if line starts with expected help indentation
                if line_no_newline.startswith(expected_help_indent):
                    # Line has proper help indentation - still in help block
                    line_type = "help_text"
                else:
                    # Indentation doesn't match expected help indent
                    potential_line_type = self._get_line_type(line_no_newline)

                    # Check if this is a keyword - keywords end help blocks
                    # when they don't have help text indentation
                    if potential_line_type in [
                        "config",
                        "menuconfig",
                        "choice",
                        "endchoice",
                        "menu",
                        "endmenu",
                        "if",
                        "endif",
                        "source",
                        "rsource",
                        "comment",
                    ]:
                        # Keyword without help indentation ends help block
                        in_help = False
                        line_type = potential_line_type
                    elif had_empty_before:
                        # Blank line before and indentation doesn't match - end help
                        in_help = False
                        line_type = potential_line_type
                    else:
                        # No blank before - treat as help text even if indentation is wrong
                        line_type = "help_text"
            else:
                line_type = self._get_line_type(line_no_newline)

            # Update help text state
            if line_type == "help":
                in_help = True

            # Check indentation
            if self.config.indent_sub_items:
                self._check_indentation_with_hierarchy(
                    line_no_newline, i, line_type, indent_level, in_help
                )
            else:
                self._check_basic_indentation(line_no_newline, i, in_help)

            # Check config name format
            if line_type == "config" or line_type == "menuconfig":
                self._check_config_name(line_no_newline, i)

            # Check comment formatting
            if line_type == "comment_line":
                self._check_comment_format(line_no_newline, i)

            # Update indentation level
            if line_type in ["menu", "if", "choice"]:
                indent_level += 1
            elif line_type in ["endmenu", "endif", "endchoice"] and indent_level > 0:
                indent_level -= 1

    def _get_line_type(self, line: str) -> str:
        """Determine the type of Kconfig line."""
        stripped = line.lstrip()

        if stripped.startswith("#"):
            return "comment_line"
        elif stripped.startswith("config"):
            return "config"
        elif stripped.startswith("menuconfig"):
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
        elif stripped.startswith("source ") or stripped.startswith("rsource "):
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

    def _check_basic_indentation(self, line: str, line_num: int, in_help: bool):
        """Check basic indentation rules (no hierarchical sub-item indenting)."""
        # Count leading whitespace
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]

        if in_help:
            # Help text should be at one tab/indent plus extra spaces
            if self.config.use_spaces:
                expected_prefix = " " * (
                    self.config.primary_indent_spaces + self.config.help_indent_spaces
                )
            else:
                expected_prefix = "\t" + " " * self.config.help_indent_spaces

            # Check if help text line (not the 'help' keyword itself)
            if not stripped.startswith("help"):
                if not indent.startswith(expected_prefix):
                    self.issues.append(
                        LintIssue(
                            line_num,
                            1,
                            "error",
                            f"Help text should be indented with {'tab + ' + str(self.config.help_indent_spaces) + ' spaces' if not self.config.use_spaces else f'{self.config.primary_indent_spaces + self.config.help_indent_spaces} spaces'}",
                        )
                    )
        else:
            # Check for tabs vs spaces
            if self.config.use_spaces:
                if "\t" in indent:
                    self.issues.append(
                        LintIssue(
                            line_num, 1, "error", "Use spaces for indentation, not tabs"
                        )
                    )
            else:
                if " " in indent and "\t" in indent:
                    # Mixed tabs and spaces (outside help text)
                    self.issues.append(
                        LintIssue(
                            line_num, 1, "error", "Mixed tabs and spaces in indentation"
                        )
                    )
                elif indent and not indent.startswith("\t") and " " in indent:
                    self.issues.append(
                        LintIssue(
                            line_num, 1, "error", "Use tabs for indentation, not spaces"
                        )
                    )

    def _check_indentation_with_hierarchy(
        self, line: str, line_num: int, line_type: str, indent_level: int, in_help: bool
    ):
        """Check indentation with hierarchical sub-item indenting."""
        stripped = line.lstrip()
        indent_len = len(line) - len(stripped)

        # Check that indentation uses the correct type (spaces vs tabs)
        if self.config.use_spaces:
            # Check that indentation is multiple of primary_indent_spaces
            if indent_len % self.config.primary_indent_spaces != 0:
                self.issues.append(
                    LintIssue(
                        line_num,
                        1,
                        "error",
                        f"Indentation must be a multiple of {self.config.primary_indent_spaces} spaces",
                    )
                )
            # Check for tabs when spaces are required
            if "\t" in line[:indent_len]:
                self.issues.append(
                    LintIssue(
                        line_num, 1, "error", "Use spaces for indentation, not tabs"
                    )
                )

    def _check_config_name(self, line: str, line_num: int):
        """Check config/menuconfig name formatting."""
        match = re.match(r"^\s*(config|menuconfig)\s+(\S+)", line)
        if not match:
            return

        config_name = match.group(2)

        # Check length
        if len(config_name) > self.config.max_option_name_length:
            self.issues.append(
                LintIssue(
                    line_num,
                    match.start(2) + 1,
                    "error",
                    f"Config name exceeds {self.config.max_option_name_length} characters",
                )
            )

        # Check uppercase if configured
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

        # Check prefix length if configured
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

    def _check_comment_format(self, line: str, line_num: int):
        """Check comment formatting (should be '# Comment' not '#Comment')."""
        stripped = line.lstrip()
        if stripped.startswith("#") and len(stripped) > 1:
            # Check if there's a space after #
            if stripped[1] != " ":
                self.issues.append(
                    LintIssue(
                        line_num,
                        len(line) - len(stripped) + 2,
                        "warning",
                        'Comments should have a space after # (use "# Comment" not "#Comment")',
                    )
                )


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

    args = parser.parse_args()

    # Start with preset or default
    if args.preset == "espidf":
        config = LinterConfig.espidf_preset()
    elif args.preset == "zephyr":
        config = LinterConfig.zephyr_preset()
    else:
        # Default to Zephyr if no preset specified
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

                # Report any unfixable issues
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

    # Exit with error code if issues found (in lint mode)
    return 1 if (not args.write and total_issues > 0) else 0


if __name__ == "__main__":
    sys.exit(main())
