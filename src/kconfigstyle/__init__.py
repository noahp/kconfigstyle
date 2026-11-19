#!/usr/bin/env python3
"""
Kconfig file linter and formatter with support for Zephyr and ESP-IDF styles.

This implementation uses a parser to build an AST, then formats by traversing the tree.
"""

import argparse
import difflib
import re
import sys
import textwrap
from dataclasses import dataclass, field, fields
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
        return cls()

    @classmethod
    def espidf_preset(cls) -> "LinterConfig":
        """Create an ESP-IDF style preset configuration."""
        return cls(
            use_spaces=True,
            help_indent_spaces=4,
            max_line_length=120,
            enforce_uppercase_configs=True,
            indent_sub_items=True,
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


# AST Node Types. line_number is 1-based, matching lint output.


@dataclass
class ASTNode:
    line_number: int = 0
    inline_comment: str = ""  # e.g. "# comment"


@dataclass
class Comment(ASTNode):
    text: str = ""  # Without the leading #


@dataclass
class EmptyLine(ASTNode):
    pass


@dataclass
class HelpText(ASTNode):
    lines: list[str] = field(default_factory=list)  # Stripped text lines


@dataclass
class ConfigOption(ASTNode):
    """A config option like 'bool', 'default', 'depends on', 'visible if', etc."""

    option_type: str = ""  # 'bool', 'default', 'depends_on', 'visible_if', ...
    value: str = ""
    condition: str = ""  # Optional trailing 'if' condition


@dataclass
class ConfigEntry(ASTNode):
    config_type: Literal["config", "configdefault", "menuconfig"] = "config"
    name: str = ""
    options: list[ASTNode] = field(default_factory=list)


@dataclass
class ChoiceEntry(ASTNode):
    name: str = ""
    options: list[ASTNode] = field(default_factory=list)
    entries: list[ASTNode] = field(default_factory=list)
    end_comment: str = ""


@dataclass
class MenuEntry(ASTNode):
    title: str = ""
    options: list[ConfigOption] = field(default_factory=list)
    statements: list[ASTNode] = field(default_factory=list)
    end_comment: str = ""


@dataclass
class IfBlock(ASTNode):
    condition: str = ""
    statements: list[ASTNode] = field(default_factory=list)
    end_comment: str = ""


@dataclass
class SourceStatement(ASTNode):
    source_type: str = "source"  # 'source', 'rsource', 'osource', 'orsource'
    path: str = ""


@dataclass
class CommentStatement(ASTNode):
    """A 'comment' statement (visible comment in menuconfig)."""

    text: str = ""
    depends: list[str] = field(default_factory=list)


@dataclass
class UnknownLine(ASTNode):
    """An unrecognized line, preserved as-is."""

    text: str = ""


BLOCK_TYPES = (ConfigEntry, ChoiceEntry, MenuEntry, IfBlock, CommentStatement)

TYPE_KEYWORDS = ("bool", "tristate", "string", "int", "hex")

_STRUCTURAL_RE = re.compile(
    r"^(config|configdefault|menuconfig|choice|endchoice|menu|endmenu|if|endif"
    r"|source|rsource|osource|orsource|comment|mainmenu)"
    # Not a prefix of a longer word (if-success) or a macro assignment (if := x)
    r"(?![\w-])(?!\s*[:+]?=)"
)
_OPTION_RE = re.compile(
    r"^(bool|tristate|string|int|hex|def_bool|def_tristate|def_int|def_hex"
    r"|def_string|prompt|default|select|imply|range|option|depends\s+on"
    r"|visible\s+if)(?:\s+(.*))?$"
)
_HELP_RE = re.compile(r"^(?:help|---help---)(?:\s|$)")


def _mask_quotes(s: str) -> str:
    """Return s with quoted string contents replaced by '_' (same length).

    Lets callers search for '#', ' if ', '&&' etc. without matching inside strings.
    """
    out = []
    quote = None
    escaped = False
    for c in s:
        if quote:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == quote:
                quote = None
                out.append(c)
                continue
            out.append("_")
        else:
            if c in "\"'":
                quote = c
            out.append(c)
    return "".join(out)


def _split_comment(s: str) -> tuple[str, str]:
    """Split a line into (code, inline_comment), ignoring '#' inside strings."""
    pos = _mask_quotes(s).find("#")
    if pos == -1:
        return s.rstrip(), ""
    return s[:pos].rstrip(), s[pos:].rstrip()


def _split_condition(value: str) -> tuple[str, str]:
    """Split 'VALUE if COND' into (VALUE, COND), ignoring ' if ' inside strings."""
    pos = _mask_quotes(value).rfind(" if ")
    if pos == -1:
        return value.strip(), ""
    return value[:pos].strip(), value[pos + 4 :].strip()


def _unquote(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] == '"':
        return s[1:-1]
    return s


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip())


def _is_structural(stripped: str) -> bool:
    return _STRUCTURAL_RE.match(stripped) is not None


def _is_option(stripped: str) -> bool:
    code = _split_comment(stripped)[0]
    return _OPTION_RE.match(code) is not None or _HELP_RE.match(code) is not None


def _keyword_rest(code: str, keyword: str) -> str:
    return code[len(keyword) :].strip()


class KconfigParser:
    """Parser for Kconfig files."""

    def __init__(self):
        self.raw: list[str] = []
        self.pos: int = 0
        # 1-based line numbers of help text bodies, for linting
        self.help_lines: set[int] = set()

    def parse(self, content: str) -> list[ASTNode]:
        """Parse Kconfig content into an AST."""
        self.raw = content.splitlines()
        self.pos = 0
        self.help_lines = set()

        statements = []
        while self.pos < len(self.raw):
            statements.append(self._parse_statement())
        return statements

    # Line access. Backslash continuations are joined lazily (not up front) so
    # help text is read verbatim and line numbers stay accurate.

    def _logical(self) -> tuple[str, int]:
        """Return (joined line, number of raw lines it spans) at pos."""
        text = self.raw[self.pos]
        span = 1
        while text.rstrip().endswith("\\"):
            text = text.rstrip()[:-1].rstrip()
            if self.pos + span >= len(self.raw):
                break
            text += " " + self.raw[self.pos + span].strip()
            span += 1
        return text, span

    def _current_line(self) -> str:
        return self._logical()[0] if self.pos < len(self.raw) else ""

    def _advance(self):
        self.pos += self._logical()[1]

    @property
    def _line_number(self) -> int:
        return self.pos + 1

    def _comment_node(self, stripped: str) -> Comment:
        node = Comment(text=stripped[1:].strip(), line_number=self._line_number)
        self._advance()
        return node

    def _parse_statement(self) -> ASTNode:
        line = self._current_line()
        stripped = line.lstrip()

        if not stripped:
            node = EmptyLine(line_number=self._line_number)
            self._advance()
            return node

        if stripped.startswith("#"):
            return self._comment_node(stripped)

        m = _STRUCTURAL_RE.match(stripped)
        parser = m and {
            "config": self._parse_config_entry,
            "configdefault": self._parse_config_entry,
            "menuconfig": self._parse_config_entry,
            "choice": self._parse_choice,
            "menu": self._parse_menu,
            "if": self._parse_if_block,
            "source": self._parse_source,
            "rsource": self._parse_source,
            "osource": self._parse_source,
            "orsource": self._parse_source,
            "comment": self._parse_comment_statement,
        }.get(m.group(1))
        if parser:
            return parser()

        node = UnknownLine(text=line, line_number=self._line_number)
        self._advance()
        return node

    def _parse_config_entry(self) -> ConfigEntry:
        """Parse a config, configdefault or menuconfig entry."""
        line = self._current_line()
        code, inline_comment = _split_comment(line.lstrip())
        config_type, name = (code.split(None, 1) + [""])[:2]

        node = ConfigEntry(
            config_type=config_type,
            name=name.strip(),
            line_number=self._line_number,
            inline_comment=inline_comment,
        )

        # A blank line followed by content at (or below) the config keyword's
        # own indent ends the entry; a comment there belongs to the next entry.
        # seen_content guards against ending before any options are parsed.
        config_indent = _indent_of(line)
        seen_content = False

        self._advance()

        while self.pos < len(self.raw):
            line = self._current_line()
            stripped = line.lstrip()

            if not stripped:
                if not self._blank_continues_config(config_indent, seen_content):
                    return node
                node.options.append(EmptyLine(line_number=self._line_number))
                self._advance()
                continue

            if _is_structural(stripped):
                break

            # Unindented lines continue the config only if they look like options
            if line[0] not in " \t" and not (
                _is_option(stripped) or stripped.startswith("#")
            ):
                break

            seen_content = True
            node.options.append(self._parse_option_line())

        return node

    def _blank_continues_config(self, config_indent: int, seen_content: bool) -> bool:
        """Whether the blank line at pos is inside the current config entry."""
        for peek in self.raw[self.pos + 1 :]:
            peek_stripped = peek.lstrip()
            if not peek_stripped:
                continue
            if _is_structural(peek_stripped) or peek[0] not in " \t":
                return False
            return not (seen_content and _indent_of(peek) <= config_indent)
        return False

    def _parse_option_line(self) -> ASTNode:
        """Parse a comment, help block, option, or unknown line inside a block."""
        line = self._current_line()
        stripped = line.lstrip()
        if stripped.startswith("#"):
            return self._comment_node(stripped)
        if _HELP_RE.match(stripped):
            return self._parse_help_block()
        option = self._parse_config_option()
        if option:
            return option
        node = UnknownLine(text=line, line_number=self._line_number)
        self._advance()
        return node

    def _parse_config_option(self) -> ConfigOption | None:
        """Parse a config option like 'bool', 'default', etc."""
        code, inline_comment = _split_comment(self._current_line().lstrip())
        m = _OPTION_RE.match(code)
        if not m:
            return None
        option_type = re.sub(r"\s+", "_", m.group(1))
        raw_value = m.group(2) or ""
        if not raw_value and option_type not in TYPE_KEYWORDS:
            return None

        value, condition = _split_condition(raw_value)
        node = ConfigOption(
            option_type=option_type,
            value=value,
            condition=condition,
            line_number=self._line_number,
            inline_comment=inline_comment,
        )
        self._advance()
        return node

    def _parse_help_block(self) -> HelpText:
        """Parse a help text block. Operates on raw lines (no continuation joining)."""
        node = HelpText(line_number=self._line_number)
        self._advance()  # Skip 'help' line

        help_indent = None
        while self.pos < len(self.raw):
            line = self.raw[self.pos]
            stripped = line.lstrip()

            if not stripped:
                next_line = (
                    self.raw[self.pos + 1] if self.pos + 1 < len(self.raw) else ""
                )
                if next_line.strip():
                    if next_line[0] not in " \t":
                        break
                    # Dedent past the help text ends the block. Leave the blank
                    # line so the parent can attribute any following comment to
                    # the next entry.
                    if help_indent is not None and _indent_of(next_line) < help_indent:
                        break
                node.lines.append("")
                self.pos += 1
                continue

            indent = _indent_of(line)
            if help_indent is None:
                if indent == 0:
                    if _is_structural(stripped):
                        break  # Empty help block
                    raise ValueError(
                        f"Line {self._line_number}: Help text must be indented. "
                        f"The first line of help text has no indentation, making it "
                        f"ambiguous where the help block ends."
                    )
                help_indent = indent

            # Anything at or past the help indent is help text, even keywords
            if indent < help_indent:
                break
            node.lines.append(stripped)
            self.help_lines.add(self._line_number)
            self.pos += 1

        # Consolidate consecutive blank lines and strip trailing ones
        node.lines = [
            ln for i, ln in enumerate(node.lines) if ln or (i > 0 and node.lines[i - 1])
        ]
        while node.lines and not node.lines[-1]:
            node.lines.pop()
        return node

    def _parse_choice(self) -> ChoiceEntry:
        code, inline_comment = _split_comment(self._current_line().lstrip())
        node = ChoiceEntry(
            name=_keyword_rest(code, "choice"),
            line_number=self._line_number,
            inline_comment=inline_comment,
        )
        self._advance()

        # Comments attach to whatever follows them (an option or an entry), so
        # a comment introducing a choice member stays above that member.
        pending: list[ASTNode] = []

        def flush(target: list[ASTNode]):
            target.extend(pending)
            pending.clear()

        while self.pos < len(self.raw):
            stripped = self._current_line().lstrip()

            if re.match(r"^endchoice\b", stripped):
                node.end_comment = _split_comment(stripped)[1]
                self._advance()
                break

            if not stripped:
                flush(node.entries if node.entries else node.options)
                self._advance()
            elif stripped.startswith("#"):
                pending.append(self._comment_node(stripped))
            elif _is_structural(stripped):
                flush(node.entries)
                node.entries.append(self._parse_statement())
            else:
                flush(node.options)
                node.options.append(self._parse_option_line())

        flush(node.entries if node.entries else node.options)
        return node

    def _parse_menu(self) -> MenuEntry:
        code, inline_comment = _split_comment(self._current_line().lstrip())
        node = MenuEntry(
            title=_unquote(_keyword_rest(code, "menu")),
            line_number=self._line_number,
            inline_comment=inline_comment,
        )
        self._advance()

        while self.pos < len(self.raw):
            stripped = self._current_line().lstrip()

            if re.match(r"^endmenu\b", stripped):
                node.end_comment = _split_comment(stripped)[1]
                self._advance()
                break

            # Menu attributes are only valid before the menu body
            header = all(isinstance(s, EmptyLine) for s in node.statements)
            if header and stripped.startswith(("depends on ", "visible if ")):
                option = self._parse_config_option()
                if option:
                    node.options.append(option)
                    continue
            node.statements.append(self._parse_statement())

        return node

    def _parse_if_block(self) -> IfBlock:
        code, inline_comment = _split_comment(self._current_line().lstrip())
        node = IfBlock(
            condition=_keyword_rest(code, "if"),
            line_number=self._line_number,
            inline_comment=inline_comment,
        )
        self._advance()

        while self.pos < len(self.raw):
            stripped = self._current_line().lstrip()
            if re.match(r"^endif\b", stripped):
                node.end_comment = _split_comment(stripped)[1]
                self._advance()
                break
            node.statements.append(self._parse_statement())

        return node

    def _parse_source(self) -> SourceStatement:
        code, inline_comment = _split_comment(self._current_line().lstrip())
        source_type, path = (code.split(None, 1) + [""])[:2]
        node = SourceStatement(
            source_type=source_type,
            path=_unquote(path.strip()),
            line_number=self._line_number,
            inline_comment=inline_comment,
        )
        self._advance()
        return node

    def _parse_comment_statement(self) -> CommentStatement:
        code, inline_comment = _split_comment(self._current_line().lstrip())
        node = CommentStatement(
            text=_unquote(_keyword_rest(code, "comment")),
            line_number=self._line_number,
            inline_comment=inline_comment,
        )
        self._advance()

        while self.pos < len(self.raw):
            line = self._current_line()
            stripped = line.lstrip()
            if not stripped or line[0] not in " \t":
                break
            if not stripped.startswith("depends on "):
                break
            node.depends.append(stripped[len("depends on ") :].strip())
            self._advance()

        return node


class KconfigFormatter:
    """Formatter for Kconfig AST."""

    def __init__(self, config: LinterConfig):
        self.config = config
        self.lines: list[str] = []

    def format(self, ast: list[ASTNode]) -> list[str]:
        """Format an AST into lines (without trailing newlines)."""
        self.lines = []
        self._format_statements(ast, 0)
        return self.lines

    @property
    def _unit(self) -> str:
        return (
            " " * self.config.primary_indent_spaces if self.config.use_spaces else "\t"
        )

    def _get_indent(self, level: int, extra_level: int = 0) -> str:
        return self._unit * (level + extra_level)

    def _get_help_indent(self, level: int) -> str:
        return self._get_indent(level, 1) + " " * self.config.help_indent_spaces

    def _sub_level(self, level: int) -> int:
        return level + (1 if self.config.indent_sub_items else 0)

    def _emit(self, code: str, inline_comment: str, indent: str):
        """Append a line, wrapping long conditions with backslash continuations."""
        comment = f"  {inline_comment}" if inline_comment else ""
        if len(code + comment) <= self.config.max_line_length:
            self.lines.append(code + comment)
            return
        wrapped = self._wrap_line(code, indent)
        wrapped[-1] += comment
        self.lines.extend(wrapped)

    def _wrap_line(self, line: str, base_indent: str) -> list[str]:
        """Wrap a long line at '&&' or '||' (outside strings) with continuations."""
        masked = _mask_quotes(line)
        separator = "&&" if "&&" in masked else "||" if "||" in masked else None
        if not separator:
            return [line]

        parts, start = [], 0
        for m in re.finditer(re.escape(separator), masked):
            parts.append(line[start : m.start()])
            start = m.end()
        parts.append(line[start:])

        cont_indent = base_indent + self._unit
        result = []
        current = parts[0].rstrip()
        for part in parts[1:]:
            part = part.strip()
            candidate = f"{current} {separator} {part}"
            if len(candidate) > self.config.max_line_length:
                result.append(current + " \\")
                current = f"{cont_indent}{separator} {part}"
            else:
                current = candidate
        result.append(current)
        return result

    def _blank(self, prev_was_empty: bool):
        if not (prev_was_empty and self.config.consolidate_empty_lines):
            self.lines.append("")

    def _format_node(self, node: ASTNode, level: int, in_config: bool = False):
        if isinstance(node, Comment):
            indent = self._get_indent(level, 1 if in_config else 0)
            self.lines.append(f"{indent}# {node.text}" if node.text else f"{indent}#")
        elif isinstance(node, UnknownLine):
            text = node.text.strip()
            self.lines.append(
                f"{self._get_indent(level, 1)}{text}" if in_config else text
            )
        elif isinstance(node, EmptyLine):
            self.lines.append("")
        elif isinstance(node, ConfigOption):
            self._format_config_option(node, level)
        elif isinstance(node, HelpText):
            self._format_help_text(node, level)
        elif isinstance(node, ConfigEntry):
            self._format_config_entry(node, level)
        elif isinstance(node, ChoiceEntry):
            self._format_choice(node, level)
        elif isinstance(node, MenuEntry):
            self._format_menu(node, level)
        elif isinstance(node, IfBlock):
            self._format_if_block(node, level)
        elif isinstance(node, SourceStatement):
            indent = self._get_indent(level)
            self._emit(
                f'{indent}{node.source_type} "{node.path}"', node.inline_comment, indent
            )
        elif isinstance(node, CommentStatement):
            indent = self._get_indent(level)
            self._emit(f'{indent}comment "{node.text}"', node.inline_comment, indent)
            for dep in node.depends:
                self.lines.append(f"{self._get_indent(level, 1)}depends on {dep}")

    def _format_statements(self, statements: list[ASTNode], level: int):
        prev_was_empty = False
        prev = None
        for stmt in statements:
            if isinstance(stmt, EmptyLine):
                self._blank(prev_was_empty)
                prev_was_empty = True
                continue
            # Always separate blocks from each other
            if (
                not prev_was_empty
                and isinstance(prev, BLOCK_TYPES)
                and isinstance(stmt, BLOCK_TYPES)
            ):
                self.lines.append("")
            prev_was_empty = False
            prev = stmt
            self._format_node(stmt, level)

    def _format_end(self, keyword: str, level: int, comment: str, has_body: bool):
        if has_body and self.lines and self.lines[-1] != "":
            self.lines.append("")
        line = f"{self._get_indent(level)}{keyword}"
        self.lines.append(f"{line}  {comment}" if comment else line)

    def _format_config_entry(self, node: ConfigEntry, level: int):
        indent = self._get_indent(level)
        self._emit(
            f"{indent}{node.config_type} {node.name}", node.inline_comment, indent
        )

        prev_was_empty = False
        for option in node.options:
            if isinstance(option, EmptyLine):
                self._blank(prev_was_empty)
                prev_was_empty = True
            else:
                prev_was_empty = False
                self._format_node(option, level, in_config=True)

    def _format_config_option(self, node: ConfigOption, level: int):
        indent = self._get_indent(level, 1)
        keyword = (
            node.option_type
            if node.option_type.startswith("def_")
            else node.option_type.replace("_", " ")
        )
        line = f"{indent}{keyword}"
        if node.value:
            line += f" {node.value}"
        if node.condition:
            line += f" if {node.condition}"
        self._emit(line, node.inline_comment, indent)

    def _format_help_text(self, node: HelpText, level: int):
        self.lines.append(f"{self._get_indent(level, 1)}help")
        help_indent = self._get_help_indent(level)
        if self.config.reflow_help_text:
            self.lines.extend(self._reflow_help_text(node.lines, help_indent))
        else:
            self.lines.extend(f"{help_indent}{ln}" if ln else "" for ln in node.lines)

    def _reflow_help_text(self, text_lines: list[str], indent: str) -> list[str]:
        """Reflow help text paragraphs to fit max line length."""
        indent_width = len(indent.replace("\t", " " * 4))
        available_width = self.config.max_line_length - indent_width
        if available_width < 20:
            available_width = 40

        result = []
        # Parser guarantees no consecutive/trailing blanks, so blanks split paragraphs
        for para in "\n".join(text_lines).split("\n\n"):
            if result:
                result.append("")
            wrapped = textwrap.wrap(
                " ".join(para.split("\n")),
                width=available_width,
                break_long_words=False,
                break_on_hyphens=False,
            )
            result.extend(f"{indent}{ln}" for ln in wrapped)
        return result

    def _format_choice(self, node: ChoiceEntry, level: int):
        indent = self._get_indent(level)
        header = f"{indent}choice {node.name}" if node.name else f"{indent}choice"
        self._emit(header, node.inline_comment, indent)

        # Blank lines in the choice header are normalized away
        for option in node.options:
            if not isinstance(option, EmptyLine):
                self._format_node(option, level, in_config=True)

        has_options = any(not isinstance(o, EmptyLine) for o in node.options)
        sub_level = self._sub_level(level)
        prev = None
        for i, entry in enumerate(node.entries):
            # Blank line before each entry, except directly after its comment
            if (i > 0 or has_options) and not isinstance(prev, Comment):
                self.lines.append("")
            self._format_node(entry, sub_level)
            prev = entry

        self._format_end("endchoice", level, node.end_comment, bool(node.entries))

    def _format_menu(self, node: MenuEntry, level: int):
        indent = self._get_indent(level)
        self._emit(f'{indent}menu "{node.title}"', node.inline_comment, indent)
        for option in node.options:
            self._format_config_option(option, level)
        self._format_statements(node.statements, self._sub_level(level))
        self._format_end("endmenu", level, node.end_comment, bool(node.statements))

    def _format_if_block(self, node: IfBlock, level: int):
        indent = self._get_indent(level)
        self._emit(f"{indent}if {node.condition}", node.inline_comment, indent)
        self._format_statements(node.statements, self._sub_level(level))
        self._format_end("endif", level, node.end_comment, bool(node.statements))


class KconfigLinter:
    """Linter for Kconfig files."""

    def __init__(self, config: LinterConfig):
        self.config = config
        self.issues: list[LintIssue] = []
        self.parser = KconfigParser()
        self.formatter = KconfigFormatter(config)

    def _issue(self, line: int, col: int | None, severity: str, message: str):
        self.issues.append(LintIssue(line, col, severity, message))

    def lint_file(self, filepath: Path) -> list[LintIssue]:
        """Lint a Kconfig file and return list of issues."""
        self.issues = []
        try:
            content = Path(filepath).read_text(encoding="utf-8")
        except Exception as e:
            self._issue(0, None, "error", f"Failed to read file: {e}")
            return self.issues

        lines = content.splitlines()
        try:
            ast = self.parser.parse(content)
        except ValueError as e:
            self._issue(0, None, "error", f"Failed to parse file: {e}")
            return self.issues

        self._lint_lines(lines, self.parser.help_lines)
        self._lint_ast(ast)
        self._lint_formatting(lines, ast)
        return self.issues

    def _lint_lines(self, lines: list[str], help_lines: set[int]):
        """Line-level checks that give a specific reason for a style violation."""
        cfg = self.config
        help_prefix = re.compile(rf"^\t+ {{{cfg.help_indent_spaces}}}")
        empty_line_count = 0

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            if line != line.rstrip():
                self._issue(
                    i,
                    len(line.rstrip()) + 1,
                    "error",
                    "Trailing whitespace not allowed",
                )

            if len(line) > cfg.max_line_length:
                self._issue(
                    i,
                    cfg.max_line_length + 1,
                    "error",
                    f"Line exceeds {cfg.max_line_length} characters",
                )

            if not stripped:
                empty_line_count += 1
                if cfg.consolidate_empty_lines and empty_line_count > 1:
                    self._issue(
                        i,
                        1,
                        "warning",
                        "Multiple consecutive empty lines (should be consolidated to one)",
                    )
                continue
            empty_line_count = 0

            if i in help_lines:
                if not cfg.use_spaces and not help_prefix.match(line):
                    self._issue(
                        i,
                        1,
                        "error",
                        f"Help text should be indented with tab + {cfg.help_indent_spaces} spaces",
                    )
                continue

            if stripped.startswith("#") and len(stripped) > 1 and stripped[1] != " ":
                self._issue(
                    i,
                    _indent_of(line) + 2,
                    "warning",
                    'Comments should have a space after # (use "# Comment" not "#Comment")',
                )

            indent = line[: _indent_of(line)]
            if not indent:
                continue
            if "\t" in indent and " " in indent:
                self._issue(i, 1, "error", "Mixed tabs and spaces in indentation")
            if cfg.use_spaces:
                if "\t" in indent:
                    self._issue(
                        i, 1, "error", "Use spaces for indentation (tabs not allowed)"
                    )
                elif len(indent) % cfg.primary_indent_spaces != 0:
                    self._issue(
                        i,
                        1,
                        "error",
                        f"Indentation should be a multiple of {cfg.primary_indent_spaces} spaces",
                    )
            elif " " in indent:
                self._issue(
                    i,
                    1,
                    "error",
                    "Use tabs for indentation (spaces not allowed except in help text)",
                )

    def _lint_formatting(self, lines: list[str], ast: list[ASTNode]):
        """Flag anything the formatter would change that wasn't already reported.

        Keeps lint and --write in agreement.
        """
        formatted = self.formatter.format(ast)
        flagged = {issue.line_number for issue in self.issues}
        matcher = difflib.SequenceMatcher(None, lines, formatted, autojunk=False)
        for tag, i1, i2, _, _ in matcher.get_opcodes():
            if tag == "equal":
                continue
            span = range(i1 + 1, max(i2, i1 + 1) + 1)
            if flagged.intersection(span):
                continue
            self._issue(
                min(i1 + 1, max(len(lines), 1)),
                None,
                "warning",
                "Formatting differs from style (run with --write to fix)",
            )

    def _lint_ast(self, nodes: list[ASTNode]):
        """Lint AST nodes for structural issues."""
        for node in nodes:
            if isinstance(node, ConfigEntry):
                self._lint_config_entry(node)
            children = getattr(node, "statements", None) or getattr(node, "entries", [])
            self._lint_ast(children)

    def _lint_config_entry(self, node: ConfigEntry):
        cfg = self.config
        col = len(node.config_type) + 2

        if len(node.name) > cfg.max_option_name_length:
            self._issue(
                node.line_number,
                col,
                "error",
                f"Config name exceeds {cfg.max_option_name_length} characters",
            )

        if cfg.enforce_uppercase_configs and node.name != node.name.upper():
            self._issue(
                node.line_number, col, "error", "Config option name must be uppercase"
            )

        if cfg.min_prefix_length > 0 and "_" in node.name:
            if len(node.name.split("_")[0]) < cfg.min_prefix_length:
                self._issue(
                    node.line_number,
                    col,
                    "warning",
                    f"Config prefix should be at least {cfg.min_prefix_length} characters",
                )

    def format_file(self, filepath: Path) -> tuple[list[str], list[LintIssue]]:
        """Format a Kconfig file. On failure, lines is empty and issues explain why."""
        self.issues = []
        try:
            content = Path(filepath).read_text(encoding="utf-8")
            ast = self.parser.parse(content)
        except Exception as e:
            self._issue(0, None, "error", f"Failed to read file: {e}")
            return [], self.issues

        return [line + "\n" for line in self.formatter.format(ast)], self.issues


def _dump_ast(nodes: list[ASTNode], indent: int = 0):
    """Dump AST structure for debugging."""
    pad = "  " * indent
    for node in nodes:
        attrs = []
        children = []
        for f in fields(node):
            value = getattr(node, f.name)
            if isinstance(value, list):
                if value:
                    children.append((f.name, value))
            elif f.name != "line_number" and value != "":
                attrs.append(f"{f.name}={value!r}")
        print(f"{pad}{type(node).__name__}({', '.join(attrs)})")
        for name, items in children:
            print(f"{pad}  {name}:")
            if all(isinstance(item, ASTNode) for item in items):
                _dump_ast(items, indent + 2)
            else:
                for item in items:
                    print(f"{pad}    {item!r}")


def _build_arg_parser() -> argparse.ArgumentParser:
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
    add = parser.add_argument
    add("files", nargs="+", type=Path, help="Kconfig files to lint/format")
    add("--version", action="version", version=f"%(prog)s {__version__}")
    add(
        "--preset",
        choices=["zephyr", "espidf"],
        default="zephyr",
        help="Use a style preset (individual options override preset values)",
    )
    add(
        "--write",
        "-w",
        action="store_true",
        help="Write formatted output back to files (format mode)",
    )

    # dest names match LinterConfig fields; None means "keep preset value"
    def flag(name, dest, help):
        add(name, dest=dest, action="store_true", default=None, help=help)

    def num(name, dest, help):
        add(name, dest=dest, type=int, help=help)

    flag("--use-spaces", "use_spaces", "Use spaces instead of tabs for indentation")
    num(
        "--primary-indent",
        "primary_indent_spaces",
        "Number of spaces for primary indentation (default: 4)",
    )
    num(
        "--help-indent",
        "help_indent_spaces",
        "Number of extra spaces for help text indentation (default: 2)",
    )
    num(
        "--max-line-length",
        "max_line_length",
        "Maximum line length (default: 100 for Zephyr, 120 for ESP-IDF)",
    )
    num(
        "--max-option-length",
        "max_option_name_length",
        "Maximum config option name length (default: 50)",
    )
    flag(
        "--uppercase-configs",
        "enforce_uppercase_configs",
        "Require config names to be uppercase",
    )
    num(
        "--min-prefix-length",
        "min_prefix_length",
        "Minimum prefix length for config names (default: 3)",
    )
    flag(
        "--indent-sub-items",
        "indent_sub_items",
        "Use hierarchical indentation for sub-items (ESP-IDF style)",
    )
    flag(
        "--consolidate-empty-lines",
        "consolidate_empty_lines",
        "Consolidate multiple consecutive empty lines into one",
    )
    flag(
        "--reflow-help",
        "reflow_help_text",
        "Reflow help text to fit within max line length",
    )
    add("--verbose", action="store_true", help="Show detailed output")
    add(
        "--dump-ast",
        action="store_true",
        help="Dump the parsed AST structure instead of linting/formatting",
    )
    add(
        "--print-formatted",
        action="store_true",
        help="Print formatted output to stdout instead of linting (for debugging)",
    )
    return parser


def _print_issues(header: str, issues: list[LintIssue]):
    print(f"\n{header}")
    for issue in sorted(issues, key=lambda x: x.line_number):
        print(f"  {issue}")


def main():
    """Main entry point for the linter."""
    args = _build_arg_parser().parse_args()

    config = getattr(LinterConfig, f"{args.preset}_preset")()
    for f in fields(LinterConfig):
        value = getattr(args, f.name, None)
        if value is not None:
            setattr(config, f.name, value)

    linter = KconfigLinter(config)
    total_issues = 0
    files_with_issues = 0
    files_formatted = 0
    banner = "=" * 60

    for filepath in args.files:
        if not filepath.exists():
            print(f"Error: File not found: {filepath}", file=sys.stderr)
            continue

        if args.dump_ast:
            try:
                ast = linter.parser.parse(filepath.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"Error parsing {filepath}: {e}", file=sys.stderr)
                continue
            print(f"\n{banner}\nAST for {filepath}\n{banner}")
            _dump_ast(ast)
            continue

        if args.print_formatted:
            formatted_lines, issues = linter.format_file(filepath)
            print(f"\n{banner}\nFormatted output for {filepath}\n{banner}")
            print("".join(formatted_lines), end="")
            if issues:
                _print_issues(f"\n{banner}\nUnfixable issues:\n{banner}", issues)
            continue

        if args.write:
            if args.verbose:
                print(f"\nFormatting {filepath}...")

            formatted_lines, issues = linter.format_file(filepath)
            if issues:
                # Formatting failed; never overwrite the file in that case
                _print_issues(f"{filepath} (not formatted):", issues)
                total_issues += len(issues)
                continue

            formatted = "".join(formatted_lines)
            try:
                if formatted != filepath.read_text(encoding="utf-8"):
                    filepath.write_text(formatted, encoding="utf-8")
                files_formatted += 1
                if args.verbose:
                    print("  ✓ Formatted")
            except Exception as e:
                print(f"Error writing {filepath}: {e}", file=sys.stderr)

            # Issues the formatter can't fix (e.g. naming) still get reported
            unfixable = linter.lint_file(filepath)
            if unfixable:
                _print_issues(f"{filepath} (unfixable issues):", unfixable)
                total_issues += len(unfixable)
        else:
            if args.verbose:
                print(f"\nLinting {filepath}...")

            issues = linter.lint_file(filepath)
            if issues:
                files_with_issues += 1
                total_issues += len(issues)
                _print_issues(f"{filepath}:", issues)

    print(f"\n{banner}")
    if args.write:
        print(f"Formatted {files_formatted} file(s)")
        if total_issues > 0:
            print(f"Warning: {total_issues} unfixable issue(s) remain")
    else:
        print(f"Total: {total_issues} issue(s) in {files_with_issues} file(s)")

    return 1 if (not args.write and total_issues > 0) else 0


if __name__ == "__main__":
    sys.exit(main())
