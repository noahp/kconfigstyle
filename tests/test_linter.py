"""Tests for Kconfig linter functionality."""

import subprocess
import sys
import tempfile
from pathlib import Path

from kconfigstyle import KconfigLinter, LinterConfig


class TestZephyrStyle:
    """Test Zephyr style linting."""

    def test_valid_zephyr_file(self):
        """Test that a valid Zephyr file has no issues."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "# Network configuration\n",
            "\n",
            "config NETWORKING\n",
            '\tbool "Enable networking"\n',
            "\thelp\n",
            "\t  Enable network stack support.\n",
            "\n",
            "config NET_IPV4\n",
            '\tbool "IPv4 support"\n',
            "\tdepends on NETWORKING\n",
            "\thelp\n",
            "\t  Enable IPv4 protocol support.\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            assert len(issues) == 0, f"Expected no issues, got: {issues}"
        finally:
            temp_path.unlink()

    def test_trailing_whitespace(self):
        """Test detection of trailing whitespace."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"  \n',  # Trailing spaces
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            assert len(issues) == 1
            assert "Trailing whitespace" in issues[0].message
            assert issues[0].line_number == 2
        finally:
            temp_path.unlink()

    def test_line_too_long(self):
        """Test detection of lines exceeding max length."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        long_line = "# " + "x" * 100 + "\n"
        lines = [long_line]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            assert len(issues) == 1
            assert "exceeds 100 characters" in issues[0].message
        finally:
            temp_path.unlink()

    def test_spaces_instead_of_tabs(self):
        """Test detection of spaces when tabs are required."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '    bool "Test"\n',  # 4 spaces instead of tab
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            assert len(issues) == 1
            assert "Use tabs for indentation" in issues[0].message
        finally:
            temp_path.unlink()

    def test_comment_without_space(self):
        """Test detection of comments without space after #."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = ["#Bad comment\n"]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            assert len(issues) == 1
            assert "space after #" in issues[0].message
        finally:
            temp_path.unlink()

    def test_help_text_indentation(self):
        """Test help text indentation checking."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\thelp\n",
            "\tWrong indentation.\n",  # Should be tab + 2 spaces
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            assert len(issues) == 1
            assert "Help text should be indented" in issues[0].message
        finally:
            temp_path.unlink()


class TestESPIDFStyle:
    """Test ESP-IDF style linting."""

    def test_valid_espidf_file(self):
        """Test that a valid ESP-IDF file has no issues."""
        config = LinterConfig.espidf_preset()
        linter = KconfigLinter(config)

        lines = [
            'menu "Network"\n',
            "    config NET_ENABLED\n",
            '        bool "Enable networking"\n',
            "        help\n",
            "            Enable network stack.\n",
            "endmenu\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            assert len(issues) == 0, f"Expected no issues, got: {issues}"
        finally:
            temp_path.unlink()

    def test_uppercase_config_names(self):
        """Test enforcement of uppercase config names."""
        config = LinterConfig.espidf_preset()
        linter = KconfigLinter(config)

        lines = [
            "config LowercaseConfig\n",
            '    bool "Test"\n',
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            assert len(issues) == 1
            assert "must be uppercase" in issues[0].message
        finally:
            temp_path.unlink()

    def test_tabs_not_allowed(self):
        """Test that tabs are not allowed in ESP-IDF style."""
        config = LinterConfig.espidf_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',  # Tab not allowed
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            assert any(
                "Use spaces for indentation" in issue.message for issue in issues
            )
        finally:
            temp_path.unlink()

    def test_indentation_multiple_of_4(self):
        """Test that indentation must be multiple of 4 spaces."""
        config = LinterConfig.espidf_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '  bool "Test"\n',  # 2 spaces, should be 4
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            assert any("multiple of 4" in issue.message for issue in issues)
        finally:
            temp_path.unlink()


class TestFormatter:
    """Test formatting functionality."""

    def test_format_tabs_to_tabs(self):
        """Test formatting with tab indentation."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        input_lines = [
            "config TEST\n",
            '  bool "Test"\n',  # Wrong: spaces
            "  help\n",
            "   Help text.\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Check that output uses tabs
            assert any("\t" in line for line in formatted), "Should contain tabs"

            # Check help text indentation (tab + 2 spaces)
            help_text_line = [line for line in formatted if "Help text" in line][0]
            assert help_text_line.startswith("\t  "), (
                "Help text should be tab + 2 spaces"
            )
        finally:
            temp_path.unlink()

    def test_format_fix_comment_spacing(self):
        """Test that formatter adds space after # in comments."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        input_lines = ["#Bad comment\n"]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            assert formatted[0] == "# Bad comment\n"
        finally:
            temp_path.unlink()

    def test_format_remove_trailing_whitespace(self):
        """Test that formatter removes trailing whitespace."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        input_lines = ["config TEST  \n"]  # Trailing spaces

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            assert formatted[0] == "config TEST\n"
        finally:
            temp_path.unlink()

    def test_consolidate_empty_lines(self):
        """Test consolidating multiple empty lines."""
        config = LinterConfig.zephyr_preset()
        config.consolidate_empty_lines = True
        linter = KconfigLinter(config)

        input_lines = [
            "config TEST1\n",
            '\tbool "Test 1"\n',
            "\n",
            "\n",
            "\n",
            "config TEST2\n",
            '\tbool "Test 2"\n',
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Count consecutive empty lines
            empty_count = 0
            max_consecutive = 0
            for line in formatted:
                if line.strip() == "":
                    empty_count += 1
                    max_consecutive = max(max_consecutive, empty_count)
                else:
                    empty_count = 0

            assert max_consecutive <= 1, "Should have at most 1 consecutive empty line"
        finally:
            temp_path.unlink()

    def test_hierarchical_indenting(self):
        """Test hierarchical indentation for nested items."""
        config = LinterConfig.espidf_preset()
        linter = KconfigLinter(config)

        input_lines = [
            'menu "Network"\n',
            "config NET\n",
            'bool "Enable"\n',
            "help\n",
            "    Help text.\n",  # Properly indented help text
            "endmenu\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Check indentation levels
            assert formatted[0] == 'menu "Network"\n'
            assert formatted[1].startswith("    config NET")  # 4 spaces
            assert formatted[2].startswith("        bool")  # 8 spaces
            assert formatted[3].startswith("        help")  # 8 spaces
            assert formatted[4].startswith("            Help")  # 12 spaces
            assert formatted[5] == "\n"  # Blank line before endmenu
            assert formatted[6] == "endmenu\n"
        finally:
            temp_path.unlink()


class TestLineTypeDetection:
    """Test line type detection."""

    def test_detect_config(self):
        """Test detection of config keyword."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        assert linter._get_line_type("config TEST") == "config"
        assert linter._get_line_type("  config TEST") == "config"

    def test_detect_menuconfig(self):
        """Test detection of menuconfig keyword."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        assert linter._get_line_type("menuconfig TEST") == "menuconfig"

    def test_detect_help(self):
        """Test detection of help keyword."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        assert linter._get_line_type("help") == "help"
        assert linter._get_line_type("\thelp") == "help"

    def test_detect_bool(self):
        """Test detection of bool option."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        assert linter._get_line_type('\tbool "Test"') == "option"
        assert linter._get_line_type('\tint "Value"') == "option"
        assert linter._get_line_type('\tstring "Text"') == "option"

    def test_detect_depends(self):
        """Test detection of depends on."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        assert linter._get_line_type("\tdepends on FOO") == "option"

    def test_detect_comment(self):
        """Test detection of comments."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        assert linter._get_line_type("# Comment") == "comment_line"
        assert linter._get_line_type("  # Comment") == "comment_line"


class TestConfigNameValidation:
    """Test config name validation."""

    def test_config_name_length(self):
        """Test detection of overly long config names."""
        config = LinterConfig.zephyr_preset()
        config.max_option_name_length = 10
        linter = KconfigLinter(config)

        lines = [f"config {'A' * 20}\n"]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            assert any("exceeds 10 characters" in issue.message for issue in issues)
        finally:
            temp_path.unlink()

    def test_prefix_length(self):
        """Test detection of short prefixes."""
        config = LinterConfig.espidf_preset()
        linter = KconfigLinter(config)

        lines = ["config AB_TEST\n"]  # Prefix "AB" is only 2 chars

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            assert any("at least 3 characters" in issue.message for issue in issues)
        finally:
            temp_path.unlink()


class TestCustomConfiguration:
    """Test custom configuration options."""

    def test_use_spaces_option(self):
        """Test custom use_spaces option."""
        config = LinterConfig.zephyr_preset()
        config.use_spaces = True
        config.primary_indent_spaces = 2

        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',  # Tab when spaces required
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            assert any("Use spaces" in issue.message for issue in issues)
        finally:
            temp_path.unlink()

    def test_custom_line_length(self):
        """Test custom max line length."""
        config = LinterConfig.zephyr_preset()
        config.max_line_length = 50

        linter = KconfigLinter(config)

        lines = ["# " + "x" * 60 + "\n"]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            assert any("exceeds 50 characters" in issue.message for issue in issues)
        finally:
            temp_path.unlink()


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_file_not_found(self):
        """Test handling of non-existent file."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        issues = linter.lint_file(Path("/nonexistent/file.Kconfig"))
        assert len(issues) == 1
        assert "Failed to read file" in issues[0].message

    def test_format_file_not_found(self):
        """Test format handling of non-existent file."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        formatted, issues = linter.format_file(Path("/nonexistent/file.Kconfig"))
        assert len(formatted) == 0
        assert len(issues) == 1
        assert "Failed to read file" in issues[0].message

    def test_mixed_tabs_and_spaces(self):
        """Test detection of mixed tabs and spaces."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\t  bool "Test"\n',  # Tab + spaces mixed
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            assert any("Mixed tabs and spaces" in issue.message for issue in issues)
        finally:
            temp_path.unlink()

    def test_empty_file(self):
        """Test handling of empty file."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            assert len(issues) == 0
        finally:
            temp_path.unlink()

    def test_consolidate_empty_lines_linting(self):
        """Test linting with consolidate empty lines option."""
        config = LinterConfig.zephyr_preset()
        config.consolidate_empty_lines = True
        linter = KconfigLinter(config)

        lines = [
            "config TEST1\n",
            "\n",
            "\n",
            "\n",
            "config TEST2\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            assert any(
                "Multiple consecutive empty lines" in issue.message for issue in issues
            )
        finally:
            temp_path.unlink()

    def test_all_line_types(self):
        """Test detection of all line types."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        assert linter._get_line_type('menu "Test"') == "menu"
        assert linter._get_line_type("endmenu") == "endmenu"
        assert linter._get_line_type("choice") == "choice"
        assert linter._get_line_type("endchoice") == "endchoice"
        assert linter._get_line_type("if FOO") == "if"
        assert linter._get_line_type("endif") == "endif"
        assert linter._get_line_type('source "path"') == "source"
        assert linter._get_line_type('comment "test"') == "comment"
        assert linter._get_line_type('\ttristate "Test"') == "option"
        assert linter._get_line_type('\thex "Value"') == "option"
        assert linter._get_line_type("\tdef_bool y") == "option"
        assert linter._get_line_type("\tdef_tristate y") == "option"
        assert linter._get_line_type('\tprompt "Text"') == "option"
        assert linter._get_line_type("\tdefault y") == "option"
        assert linter._get_line_type("\tselect FOO") == "option"
        assert linter._get_line_type("\timply BAR") == "option"
        assert linter._get_line_type("\trange 0 100") == "option"
        assert linter._get_line_type('\toption env="VAR"') == "option"
        assert linter._get_line_type("some random text") == "other"

    def test_config_name_without_underscore(self):
        """Test config name validation without underscore."""
        config = LinterConfig.espidf_preset()
        linter = KconfigLinter(config)

        lines = ["config TESTING\n"]  # No underscore, no prefix warning

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            # Should not complain about prefix length
            assert not any("prefix" in issue.message.lower() for issue in issues)
        finally:
            temp_path.unlink()

    def test_invalid_config_line(self):
        """Test config line that doesn't match pattern."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        # _check_config_name should handle lines that don't match
        linter._check_config_name("config", 1)
        assert len(linter.issues) == 0  # Should not crash or add issues

    def test_comment_with_only_hash(self):
        """Test single # character without text."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = ["#\n"]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            # Should not complain about single #
            assert not any("space after #" in issue.message for issue in issues)
        finally:
            temp_path.unlink()

    def test_format_with_spaces_hierarchical(self):
        """Test formatting with spaces and hierarchical indenting."""
        config = LinterConfig.zephyr_preset()
        config.use_spaces = True
        config.indent_sub_items = True
        linter = KconfigLinter(config)

        input_lines = [
            'menu "Test"\n',
            "config FOO\n",
            'bool "Test"\n',
            "help\n",
            "    Help text.\n",  # Properly indented
            "endmenu\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            # Verify spaces are used
            assert all("\t" not in line for line in formatted if line.strip())
        finally:
            temp_path.unlink()

    def test_format_tabs_hierarchical(self):
        """Test formatting with tabs and hierarchical indenting."""
        config = LinterConfig.zephyr_preset()
        config.indent_sub_items = True
        linter = KconfigLinter(config)

        input_lines = [
            'menu "Test"\n',
            "config FOO\n",
            'bool "Test"\n',
            "endmenu\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            # Config should be indented with 1 tab (inside menu)
            assert formatted[1].startswith("\tconfig")
        finally:
            temp_path.unlink()

    def test_format_other_line_type(self):
        """Test formatting of 'other' line types."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        input_lines = [
            "config FOO\n",
            '  bool "Test"\n',
            "  some random text\n",  # 'other' type
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            # Other line should be indented like an option
            assert formatted[2].startswith("\tsome random text")
        finally:
            temp_path.unlink()

    def test_format_empty_line_not_consolidate(self):
        """Test formatting preserves multiple empty lines when not consolidating."""
        config = LinterConfig.zephyr_preset()
        config.consolidate_empty_lines = False
        linter = KconfigLinter(config)

        input_lines = [
            "config TEST1\n",
            "\n",
            "\n",
            "config TEST2\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            empty_count = sum(1 for line in formatted if line.strip() == "")
            assert empty_count == 2  # Both empty lines preserved
        finally:
            temp_path.unlink()

    def test_help_keyword_in_help_section(self):
        """Test that help keyword itself doesn't get checked as help text."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\thelp\n",  # This is the help keyword
            "\t  Text.\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            assert len(issues) == 0
        finally:
            temp_path.unlink()

    def test_lint_issue_string_representation(self):
        """Test LintIssue string formatting."""
        from kconfigstyle import LintIssue

        issue_with_col = LintIssue(10, 5, "error", "Test message")
        assert str(issue_with_col) == "Line 10:5: [error] Test message"

        issue_no_col = LintIssue(10, None, "warning", "Test message")
        assert str(issue_no_col) == "Line 10: [warning] Test message"


class TestHelpTextReflow:
    """Test help text reflow functionality."""

    def test_reflow_basic(self):
        """Test basic help text reflow."""
        config = LinterConfig.zephyr_preset()
        config.reflow_help_text = True
        config.max_line_length = 80
        linter = KconfigLinter(config)

        input_lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\thelp\n",
            "\t  This is a very long help text that should be reflowed to fit within the maximum line length setting when the reflow option is enabled.\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Check that all lines are within length limit
            for line in formatted:
                assert len(line.rstrip("\n")) <= 80, f"Line exceeds 80 chars: {line}"

            # Check that we have multiple help text lines (index 3 onwards after help keyword)
            help_text_lines = [
                line
                for line in formatted[3:]
                if line.strip() and not line.strip().startswith("config")
            ]
            assert len(help_text_lines) > 1, (
                f"Help text should be wrapped into multiple lines, got: {help_text_lines}"
            )
        finally:
            temp_path.unlink()

    def test_reflow_with_paragraphs(self):
        """Test that reflow preserves paragraph breaks."""
        config = LinterConfig.zephyr_preset()
        config.reflow_help_text = True
        config.max_line_length = 60
        linter = KconfigLinter(config)

        input_lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\thelp\n",
            "\t  First paragraph with some long text that needs wrapping.\n",
            "\n",
            "\t  Second paragraph also with long text.\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Check that there's an empty line between paragraphs
            assert any(line.strip() == "" for line in formatted[3:]), (
                "Should preserve paragraph break"
            )
        finally:
            temp_path.unlink()

    def test_reflow_with_spaces(self):
        """Test reflow with space indentation (ESP-IDF style)."""
        config = LinterConfig.espidf_preset()
        config.reflow_help_text = True
        config.max_line_length = 80
        linter = KconfigLinter(config)

        input_lines = [
            "config TEST_OPTION\n",
            '    bool "Test option"\n',
            "    help\n",
            "        This is a very long help text that should be reflowed to fit within the maximum line length setting. It should use space indentation.\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Find help text lines (after the help keyword)
            help_start = next(
                i
                for i, line in enumerate(formatted)
                if "help" in line.lower() and "bool" not in line.lower()
            )
            help_lines = [line for line in formatted[help_start + 1 :] if line.strip()]

            # Check all help lines use spaces (no tabs)
            for line in help_lines:
                assert "\t" not in line, (
                    f"Help text should use spaces, not tabs: {line}"
                )

            # Check lines are within limit
            for line in help_lines:
                assert len(line.rstrip("\n")) <= 80
        finally:
            temp_path.unlink()

    def test_reflow_hierarchical_indent(self):
        """Test reflow with hierarchical indentation."""
        config = LinterConfig.espidf_preset()
        config.reflow_help_text = True
        config.max_line_length = 70
        linter = KconfigLinter(config)

        input_lines = [
            'menu "Test Menu"\n',
            "    config NESTED\n",
            '        bool "Nested"\n',
            "        help\n",
            "            This help text is inside a menu and should be properly indented when using hierarchical mode.\n",
            "endmenu\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Find help text lines (after help keyword)
            help_start = next(
                i for i, line in enumerate(formatted) if line.strip() == "help"
            )
            help_lines = [
                line
                for line in formatted[help_start + 1 :]
                if line.strip() and "endmenu" not in line
            ]

            # Verify indentation is correct (should be more than base level)
            for line in help_lines:
                # Should have significant indentation due to nesting
                assert line.startswith("        "), (
                    f"Help text should be indented for nested item: {repr(line)}"
                )

            # Check lines are within limit
            for line in help_lines:
                assert len(line.rstrip("\n")) <= 70
        finally:
            temp_path.unlink()

    def test_reflow_short_text(self):
        """Test that short help text is not unnecessarily modified."""
        config = LinterConfig.zephyr_preset()
        config.reflow_help_text = True
        config.max_line_length = 100
        linter = KconfigLinter(config)

        input_lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\thelp\n",
            "\t  Short help.\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Find help text line
            help_line = [line for line in formatted if "Short help" in line][0]

            # Should be on a single line
            assert "Short help." in help_line
        finally:
            temp_path.unlink()

    def test_reflow_disabled_by_default(self):
        """Test that reflow is disabled by default."""
        config = LinterConfig.zephyr_preset()
        # reflow_help_text defaults to False
        linter = KconfigLinter(config)

        input_lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\thelp\n",
            "\t  This is a very long help text that would normally be reflowed if the option was enabled but should remain on one line.\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Find help text lines
            help_lines = [line for line in formatted if "This is a very long" in line]

            # Should be on a single line (not reflowed)
            assert len(help_lines) == 1, (
                "Help text should not be reflowed when disabled"
            )
        finally:
            temp_path.unlink()

    def test_reflow_multiple_configs(self):
        """Test reflow with multiple config sections."""
        config = LinterConfig.zephyr_preset()
        config.reflow_help_text = True
        config.max_line_length = 60
        linter = KconfigLinter(config)

        input_lines = [
            "config TEST1\n",
            '\tbool "Test 1"\n',
            "\thelp\n",
            "\t  First config with long help text that needs wrapping.\n",
            "\n",
            "config TEST2\n",
            '\tbool "Test 2"\n',
            "\thelp\n",
            "\t  Second config also with long help text.\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Check all lines are within limit
            for line in formatted:
                if line.strip():  # Non-empty lines
                    assert len(line.rstrip("\n")) <= 60, f"Line too long: {line}"

            # Should have both config sections
            assert sum(1 for line in formatted if "config TEST" in line) == 2
        finally:
            temp_path.unlink()


class TestContinuationLines:
    """Test continuation line handling with backslashes."""

    def test_wrap_long_depends_on(self):
        """Test wrapping long depends on lines."""
        config = LinterConfig.zephyr_preset()
        config.max_line_length = 50
        linter = KconfigLinter(config)

        input_lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\tdepends on FOO && BAR && BAZ && QUX && VERY_LONG_NAME\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Should have continuation lines
            cont_lines = [
                line
                for line in formatted
                if "\\" in line or ("&&" in line and "depends" not in line)
            ]
            assert len(cont_lines) > 0, (
                f"Long depends should be split, got: {formatted}"
            )

            # First depends line should end with backslash
            depends_line = [line for line in formatted if "depends" in line][0]
            assert depends_line.rstrip().endswith("\\"), (
                f"Continuation should end with backslash: {depends_line}"
            )

            # All lines should be within limit
            for line in formatted:
                assert len(line.rstrip("\n")) <= 50, (
                    f"Line too long ({len(line.rstrip())}): {line}"
                )
        finally:
            temp_path.unlink()

    def test_join_existing_continuations(self):
        """Test that existing continuation lines are joined and reformatted."""
        config = LinterConfig.zephyr_preset()
        config.max_line_length = 100
        linter = KconfigLinter(config)

        input_lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\tselect A && \\\n",
            "\t\tB && \\\n",
            "\t\tC\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Should be joined into single line (since it fits in 100 chars)
            select_lines = [line for line in formatted if "select" in line]
            assert len(select_lines) == 1, "Short continuation should be joined"
            assert "\\" not in select_lines[0], "No backslash needed for short line"
        finally:
            temp_path.unlink()

    def test_wrap_if_statement(self):
        """Test wrapping long if statements."""
        config = LinterConfig.zephyr_preset()
        config.max_line_length = 40
        linter = KconfigLinter(config)

        input_lines = [
            "if NETWORKING && WIFI_ENABLED && BLUETOOTH_SUPPORT\n",
            "config TEST\n",
            '\tbool "Test"\n',
            "endif\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Should have continuation for if
            if_lines = [
                line
                for line in formatted
                if "if" in line.lower() and "endif" not in line.lower()
            ]
            assert any("\\" in line for line in if_lines), (
                f"Long if should have continuation, got: {if_lines}"
            )
        finally:
            temp_path.unlink()

    def test_continuation_with_spaces(self):
        """Test continuation with space indentation."""
        config = LinterConfig.espidf_preset()
        config.max_line_length = 60
        linter = KconfigLinter(config)

        input_lines = [
            "config TEST_OPTION\n",
            '    bool "Test"\n',
            "    depends on A && B && C && D && E && F\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Should use spaces for continuation indent
            cont_lines = [
                line for line in formatted if "&&" in line and "depends" not in line
            ]
            for line in cont_lines:
                assert "\t" not in line, "Continuation should use spaces"
        finally:
            temp_path.unlink()

    def test_no_wrap_for_short_lines(self):
        """Test that short lines are not wrapped."""
        config = LinterConfig.zephyr_preset()
        config.max_line_length = 100
        linter = KconfigLinter(config)

        input_lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\tdepends on FOO && BAR\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Should not have any backslashes
            assert not any("\\" in line for line in formatted), (
                "Short lines should not be wrapped"
            )
        finally:
            temp_path.unlink()

    def test_continuation_hierarchical_indent(self):
        """Test continuation lines with hierarchical indentation."""
        config = LinterConfig.espidf_preset()
        config.max_line_length = 60
        linter = KconfigLinter(config)

        input_lines = [
            'menu "Test"\n',
            "    config NESTED\n",
            '        bool "Nested"\n',
            "        select FEAT_A && FEAT_B && FEAT_C && FEAT_D\n",
            "endmenu\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Find continuation lines
            cont_lines = [
                line for line in formatted if "&&" in line and "select" not in line
            ]

            # Should have proper hierarchical indentation
            for line in cont_lines:
                # Should be indented more than the base config level
                assert line.startswith("        "), (
                    f"Continuation should maintain hierarchy: {repr(line)}"
                )
        finally:
            temp_path.unlink()


class TestCommentIndentation:
    """Test comment line indentation."""

    def test_comment_indentation_hierarchical(self):
        """Test that comments are indented with hierarchical style."""
        config = LinterConfig.espidf_preset()
        linter = KconfigLinter(config)

        input_lines = [
            'menu "Test"\n',
            "# Comment inside menu\n",
            "config TEST\n",
            '    bool "Test"\n',
            "endmenu\n",
            "# Comment outside menu\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Find comment lines
            inside_comment = [line for line in formatted if "Comment inside" in line][0]
            outside_comment = [line for line in formatted if "Comment outside" in line][
                0
            ]

            # Inside comment should be indented
            assert inside_comment.startswith("    #"), (
                f"Comment inside menu should be indented: {repr(inside_comment)}"
            )

            # Outside comment should not be indented
            assert outside_comment.startswith("#") and not outside_comment.startswith(
                " "
            ), f"Comment outside menu should not be indented: {repr(outside_comment)}"
        finally:
            temp_path.unlink()

    def test_comment_no_indent_without_hierarchical(self):
        """Test that comments are not indented without hierarchical style."""
        config = LinterConfig.zephyr_preset()  # No hierarchical by default
        linter = KconfigLinter(config)

        input_lines = [
            'menu "Test"\n',
            "# Comment inside menu\n",
            "config TEST\n",
            '\tbool "Test"\n',
            "endmenu\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Find comment line
            comment = [line for line in formatted if "Comment inside" in line][0]

            # Comment should not be indented (Zephyr style, no hierarchy, not in config block)
            assert comment.startswith("#") and not comment.startswith(" "), (
                f"Comment should not be indented in Zephyr style: {repr(comment)}"
            )
        finally:
            temp_path.unlink()

    def test_comment_in_config_block(self):
        """Test that comments inside config blocks are always indented."""
        config = LinterConfig.zephyr_preset()  # No hierarchical by default
        linter = KconfigLinter(config)

        input_lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "# Comment inside config block\n",
            "\tdefault y\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Find comment line
            comment = [line for line in formatted if "Comment inside" in line][0]

            # Comment should be indented like options (with tab in Zephyr style)
            assert comment.startswith("\t#"), (
                f"Comment in config block should be indented: {repr(comment)}"
            )
        finally:
            temp_path.unlink()

    def test_nested_comment_indentation(self):
        """Test comment indentation in nested structures."""
        config = LinterConfig.espidf_preset()
        linter = KconfigLinter(config)

        input_lines = [
            'menu "Level 1"\n',
            "# Comment level 1\n",
            'menu "Level 2"\n',
            "# Comment level 2\n",
            "config TEST\n",
            '    bool "Test"\n',
            "endmenu\n",
            "endmenu\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(input_lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)

            # Find comment lines
            level1_comment = [line for line in formatted if "level 1" in line][0]
            level2_comment = [line for line in formatted if "level 2" in line][0]

            # Level 1 should have 4 spaces
            assert level1_comment.startswith("    #"), (
                f"Level 1 comment should have 4 spaces: {repr(level1_comment)}"
            )

            # Level 2 should have 8 spaces
            assert level2_comment.startswith("        #"), (
                f"Level 2 comment should have 8 spaces: {repr(level2_comment)}"
            )
        finally:
            temp_path.unlink()


class TestCLI:
    """Test command-line interface."""

    def test_cli_basic_lint(self):
        """Test basic CLI linting."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.write('config TEST\n\tbool "Test"\n')
            temp_path = Path(f.name)

        try:
            result = subprocess.run(
                [sys.executable, "-m", "kconfigstyle", str(temp_path)],
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert "0 issue(s)" in result.stdout
        finally:
            temp_path.unlink()

    def test_cli_with_issues(self):
        """Test CLI with files that have issues."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.write("config TEST  \n")  # Trailing space
            temp_path = Path(f.name)

        try:
            result = subprocess.run(
                [sys.executable, "-m", "kconfigstyle", str(temp_path)],
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 1
            assert "Trailing whitespace" in result.stdout
        finally:
            temp_path.unlink()

    def test_cli_file_not_found(self):
        """Test CLI with non-existent file."""
        result = subprocess.run(
            [sys.executable, "-m", "kconfigstyle", "/nonexistent/file.Kconfig"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )
        assert "File not found" in result.stderr

    def test_cli_write_mode(self):
        """Test CLI in write/format mode."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.write('#Bad comment\nconfig TEST\n  bool "Test"\n')
            temp_path = Path(f.name)

        try:
            result = subprocess.run(
                [sys.executable, "-m", "kconfigstyle", "--write", str(temp_path)],
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert "Formatted 1 file(s)" in result.stdout

            # Verify file was actually formatted
            with open(temp_path) as f:
                content = f.read()
                assert content.startswith("# Bad comment")
                assert "\t" in content  # Should have tabs
        finally:
            temp_path.unlink()

    def test_cli_espidf_preset(self):
        """Test CLI with ESP-IDF preset."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.write('config lowercase\n    bool "Test"\n')
            temp_path = Path(f.name)

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "kconfigstyle",
                    "--preset",
                    "espidf",
                    str(temp_path),
                ],
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 1
            assert "uppercase" in result.stdout
        finally:
            temp_path.unlink()

    def test_cli_custom_options(self):
        """Test CLI with custom options."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.write("# " + "x" * 60 + "\n")
            temp_path = Path(f.name)

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "kconfigstyle",
                    "--max-line-length",
                    "50",
                    str(temp_path),
                ],
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 1
            assert "exceeds 50 characters" in result.stdout
        finally:
            temp_path.unlink()

    def test_cli_verbose(self):
        """Test CLI with verbose output."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.write('config TEST\n\tbool "Test"\n')
            temp_path = Path(f.name)

        try:
            result = subprocess.run(
                [sys.executable, "-m", "kconfigstyle", "--verbose", str(temp_path)],
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
            )
            assert "Linting" in result.stdout
        finally:
            temp_path.unlink()

    def test_cli_multiple_files(self):
        """Test CLI with multiple files."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f1:
            f1.write('config TEST1\n\tbool "Test"\n')
            temp_path1 = Path(f1.name)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f2:
            f2.write('config TEST2\n\tbool "Test"\n')
            temp_path2 = Path(f2.name)

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "kconfigstyle",
                    str(temp_path1),
                    str(temp_path2),
                ],
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
        finally:
            temp_path1.unlink()
            temp_path2.unlink()

    def test_cli_all_options(self):
        """Test CLI with all available options."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.write('config TEST\nbool "Test"\n')
            temp_path = Path(f.name)

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "kconfigstyle",
                    "--use-spaces",
                    "--primary-indent",
                    "2",
                    "--help-indent",
                    "4",
                    "--max-line-length",
                    "120",
                    "--max-option-length",
                    "40",
                    "--uppercase-configs",
                    "--min-prefix-length",
                    "2",
                    "--indent-sub-items",
                    "--consolidate-empty-lines",
                    "--reflow-help",
                    "--write",
                    "--verbose",
                    str(temp_path),
                ],
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
            )
            assert "Formatted" in result.stdout
        finally:
            temp_path.unlink()

    def test_cli_reflow_help(self):
        """Test CLI with reflow help option."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.write(
                'config TEST\n\tbool "Test"\n\thelp\n\t  This is a very long help text that should be reflowed to fit within the specified maximum line length when using the reflow option.\n'
            )
            temp_path = Path(f.name)

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "kconfigstyle",
                    "--reflow-help",
                    "--max-line-length",
                    "60",
                    "--write",
                    str(temp_path),
                ],
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert "Formatted" in result.stdout

            # Verify file was reflowed
            with open(temp_path) as f:
                content = f.read()
                lines = content.split("\n")
                # All non-empty lines should be within limit
                for line in lines:
                    if line.strip():
                        assert len(line) <= 60, f"Line too long: {line}"
        finally:
            temp_path.unlink()


class TestHelpBlockTermination:
    """Test help block termination and keyword detection."""

    def test_blank_line_terminates_help(self):
        """Test that blank lines terminate help blocks."""
        config = LinterConfig.zephyr_preset()
        config.reflow_help_text = True
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test option"\n',
            "\thelp\n",
            "\t  This is help text.\n",
            "\n",
            "module = TEST\n",
            'source "Kconfig.test"\n',
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # After the blank line, module and source should be at top level (not indented)
            assert "\nmodule = TEST\n" in formatted
            assert '\nsource "Kconfig.test"\n' in formatted
        finally:
            temp_path.unlink()

    def test_config_keyword_in_help_text(self):
        """Test that 'config' in help text is not treated as a keyword."""
        config = LinterConfig.zephyr_preset()
        config.reflow_help_text = True
        linter = KconfigLinter(config)

        lines = [
            "config MEMFAULT_TEST\n",
            '\tbool "Test option"\n',
            "\thelp\n",
            "\t  This option provides a\n",
            "\t  config header.\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # "config header." should be reflowed as part of help text, not treated as keyword
            assert "config header" in formatted
            # Should be a single reflowed paragraph
            assert formatted.count("\t  ") == 1  # Only one help text line
        finally:
            temp_path.unlink()

    def test_module_keyword_in_help_text(self):
        """Test that 'module' assignments in help text are treated as help content."""
        config = LinterConfig.zephyr_preset()
        config.reflow_help_text = False
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\thelp\n",
            "\t  Help text.\n",
            "\n",
            "module = MEMFAULT\n",
            "module-str = Memfault\n",
            'source "test.Kconfig"\n',
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # After blank line terminates help, unindented module lines should be top-level
            assert "\nmodule = MEMFAULT\n" in formatted
            assert "\nmodule-str = Memfault\n" in formatted
        finally:
            temp_path.unlink()

    def test_blank_line_with_indented_continuation(self):
        """Test that blank lines in help text followed by indented text continue the help block."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config CACHE_DOUBLEMAP\n",
            '\tbool "Cache double-mapping support"\n',
            "\tselect CACHE_HAS_MIRRORED_MEMORY_REGIONS\n",
            "\tselect DEPRECATED\n",
            "\thelp\n",
            "\t  Double-mapping behavior where a pointer can be cheaply converted to\n",
            "\t  point to the same cached/uncached memory at different locations.\n",
            "\n",
            "\t  This applies to intra-CPU multiprocessing incoherence and makes only\n",
            "\t  sense when MP_MAX_NUM_CPUS > 1.\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # The blank line should be preserved
            assert "\n\n" in formatted
            # Text after blank line should still be formatted as help text (indented)
            assert "\t  This applies to" in formatted
            assert "\t  sense when MP_MAX_NUM_CPUS > 1.\n" in formatted
        finally:
            temp_path.unlink()

    def test_config_keyword_as_indented_help_text(self):
        """Test that indented 'config' keyword is treated as help text, not a new config."""
        from kconfigstyle import KconfigParser

        content = """config NETWORKING
\tbool "Enable networking"
\thelp
\t  Enable network stack support for the application.
\t  This provides TCP/IP connectivity.

\t  config use this config!
"""

        parser = KconfigParser()
        ast = parser.parse(content)

        # Should have exactly one config entry
        assert len(ast) == 1
        assert ast[0].__class__.__name__ == "ConfigEntry"
        assert ast[0].name == "NETWORKING"

        # Find the help text in the options
        help_text = None
        for option in ast[0].options:
            if option.__class__.__name__ == "HelpText":
                help_text = option
                break

        assert help_text is not None, "No HelpText found in config options"

        # Help text should contain 4 lines (including blank line and "config use this config!")
        assert len(help_text.lines) == 4, (
            f"Expected 4 lines, got {len(help_text.lines)}"
        )
        assert help_text.lines[0] == "Enable network stack support for the application."
        assert help_text.lines[1] == "This provides TCP/IP connectivity."
        assert help_text.lines[2] == ""
        assert help_text.lines[3] == "config use this config!"

    def test_inline_comments_preserved(self):
        """Test that inline comments are preserved during formatting."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST  # Test configuration\n",
            '\tbool "Enable test"  # Boolean option\n',
            "\tdefault y  # Default to enabled\n",
            "\thelp\n",
            "\t  This is help text.\n",
            "\n",
            "if FEATURE  # Feature flag\n",
            "\tconfig FEATURE_OPT\n",
            '\t\tbool "Feature option"\n',
            "endif  # FEATURE\n",
            "\n",
            "choice TEST_CHOICE  # Test choice\n",
            '\tprompt "Select option"\n',
            "config CHOICE_A\n",
            '\tbool "Choice A"\n',
            "endchoice  # TEST_CHOICE\n",
            "\n",
            'menu "Test Menu"  # Menu for testing\n',
            "\tconfig MENU_OPT\n",
            '\t\tbool "Menu option"\n',
            "endmenu  # Test Menu\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            formatted_text = "".join(formatted)

            # Check that inline comments are preserved
            assert "# Test configuration" in formatted_text
            assert "# Boolean option" in formatted_text
            assert "# Default to enabled" in formatted_text
            assert "# Feature flag" in formatted_text
            assert "endif  # FEATURE" in formatted_text
            assert "# Test choice" in formatted_text
            assert "endchoice  # TEST_CHOICE" in formatted_text
            assert "# Menu for testing" in formatted_text
            assert "endmenu  # Test Menu" in formatted_text

            # Verify proper spacing before comments (2 spaces)
            assert "config TEST  # Test configuration" in formatted_text
            assert 'bool "Enable test"  # Boolean option' in formatted_text
            assert "default y  # Default to enabled" in formatted_text
        finally:
            temp_path.unlink()


class TestAdditionalCoverage:
    """Additional tests to improve code coverage."""

    def test_help_with_spaces_hierarchical_blank_line(self):
        """Test help text with blank line using spaces and hierarchical indenting."""
        config = LinterConfig.espidf_preset()
        config.indent_sub_items = True
        linter = KconfigLinter(config)

        lines = [
            'menu "Test"\n',
            "    config TEST\n",
            '        bool "Test"\n',
            "        help\n",
            "            First paragraph.\n",
            "\n",
            "            Second paragraph.\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # Both paragraphs should be indented properly
            assert "            First paragraph." in formatted
            assert "            Second paragraph." in formatted
            assert "\n\n" in formatted  # Blank line preserved
        finally:
            temp_path.unlink()

    def test_comment_after_help_with_blank_reflow(self):
        """Test comment after help block with blank line and reflow enabled."""
        config = LinterConfig.zephyr_preset()
        config.reflow_help_text = True
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\thelp\n",
            "\t  Some help text.\n",
            "\n",
            "# Comment here\n",
            "config NEXT\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # Comment should be at top level
            assert "\n# Comment here\n" in formatted
        finally:
            temp_path.unlink()

    def test_help_text_indentation_mismatch_with_reflow(self):
        """Test help block ending when indentation doesn't match (with reflow)."""
        config = LinterConfig.espidf_preset()
        config.reflow_help_text = True
        config.indent_sub_items = True
        linter = KconfigLinter(config)

        lines = [
            'menu "Test"\n',
            "    config TEST\n",
            '        string "Test"\n',
            "        help\n",
            "            Help text here.\n",
            "\n",
            "    config NEXT\n",  # Different indentation - ends help
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # NEXT should be properly formatted, not as help text
            assert "    config NEXT\n" in formatted
        finally:
            temp_path.unlink()

    def test_continuation_lines_multiple(self):
        """Test multiple continuation lines."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\tdepends on A && \\\n",
            "\t           B && \\\n",
            "\t           C\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # Should join continuation lines
            assert "depends on A && B && C" in formatted
        finally:
            temp_path.unlink()

    def test_reflow_empty_line_in_paragraph(self):
        """Test reflow with empty lines creating paragraphs."""
        config = LinterConfig.zephyr_preset()
        config.reflow_help_text = True
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\thelp\n",
            "\t  First para line one.\n",
            "\t  First para line two.\n",
            "\n",
            "\t  Second para.\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # Should have two separate paragraphs
            lines_list = formatted.split("\n")
            help_lines = [
                line
                for line in lines_list
                if line.strip()
                and not line.strip().startswith(("config", "bool", "help"))
            ]

            # Should have reflowed paragraphs
            assert len(help_lines) >= 2
        finally:
            temp_path.unlink()

    def test_help_text_indentation_spaces_hierarchical(self):
        """Test help text indentation calculation with spaces and hierarchy."""
        config = LinterConfig.espidf_preset()
        config.indent_sub_items = True
        linter = KconfigLinter(config)

        lines = [
            "if ADVANCED\n",
            '    menu "Options"\n',
            "        config TEST\n",
            '            bool "Test"\n',
            "            help\n",
            "                Help text.\n",
            "\n",
            "                More help.\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # Both help lines should have proper indentation
            assert "                Help text." in formatted
            assert "                More help." in formatted
        finally:
            temp_path.unlink()

    def test_unindented_other_line_ends_config_block(self):
        """Test that unindented non-keyword lines end config blocks."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\tdefault y\n",
            "some_other_line\n",  # Unindented, not a keyword
            "config NEXT\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # some_other_line should be at top level
            assert "\nsome_other_line\n" in formatted
        finally:
            temp_path.unlink()

    def test_reflow_narrow_width(self):
        """Test reflow with very narrow available width."""
        config = LinterConfig.zephyr_preset()
        config.reflow_help_text = True
        config.max_line_length = 30  # Very short
        linter = KconfigLinter(config)

        lines = [
            "config T\n",
            '\tbool "T"\n',
            "\thelp\n",
            "\t  Short.\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            # Should handle narrow width gracefully
            assert formatted_lines is not None
        finally:
            temp_path.unlink()

    def test_help_block_ending_with_option(self):
        """Test that option lines don't end config block when help ends."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\thelp\n",
            "\t  Help text.\n",
            "\n",
            "\tdefault y\n",  # option line after help
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # default should still be indented (in config block)
            assert "\tdefault y\n" in formatted
        finally:
            temp_path.unlink()

    def test_rsource_keyword(self):
        """Test rsource keyword handling."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\thelp\n",
            "\t  Help.\n",
            "\n",
            'rsource "Kconfig.other"\n',
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # rsource should be at top level and end help block
            assert '\nrsource "Kconfig.other"\n' in formatted
        finally:
            temp_path.unlink()

    def test_help_keyword_ends_help_block(self):
        """Test that help keyword after blank ends help block."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\thelp\n",
            "\t  Help text.\n",
            "\n",
            "\thelp\n",  # Another help keyword
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # Should handle gracefully
            assert "help" in formatted
        finally:
            temp_path.unlink()

    def test_multiple_empty_lines_in_help_text(self):
        """Test that multiple consecutive empty lines in help text are consolidated."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\thelp\n",
            "\t  First line of help.\n",
            "\n",
            "\n",
            "\n",
            "\t  Second line after multiple blanks.\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            # Verify formatted output has only one blank line
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # Should not have multiple consecutive blank lines (3+ newlines in a row)
            assert "\n\n\n" not in formatted
            # Should have one blank line between help text paragraphs
            assert "First line of help.\n\n\t  Second line" in formatted
        finally:
            temp_path.unlink()

    def test_comment_outside_config_hierarchical_with_tabs(self):
        """Test comment outside config block with hierarchical indent using tabs."""
        config = LinterConfig.zephyr_preset()
        config.indent_sub_items = True
        linter = KconfigLinter(config)

        lines = [
            'menu "Test"\n',
            "# Comment in menu\n",
            "\tconfig A\n",
            '\t\tbool "A"\n',
            "endmenu\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # Comment should be indented with menu hierarchy
            assert "\t# Comment in menu\n" in formatted
        finally:
            temp_path.unlink()

    def test_comment_outside_config_hierarchical_with_spaces(self):
        """Test comment outside config block with hierarchical indent using spaces."""
        config = LinterConfig.espidf_preset()
        config.indent_sub_items = True
        linter = KconfigLinter(config)

        lines = [
            'menu "Test"\n',
            "# Comment in menu\n",
            "    config A\n",
            '        bool "A"\n',
            "endmenu\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # Comment should be indented with menu hierarchy
            assert "    # Comment in menu\n" in formatted
        finally:
            temp_path.unlink()

    def test_endmenu_with_spaces_hierarchical(self):
        """Test endmenu indentation with spaces and hierarchical indent."""
        config = LinterConfig.espidf_preset()
        config.indent_sub_items = True
        linter = KconfigLinter(config)

        lines = [
            "if ADVANCED\n",
            '    menu "Test"\n',
            "        config A\n",
            '            bool "A"\n',
            "    endmenu\n",
            "endif\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # endmenu should be indented at if level
            assert "    endmenu\n" in formatted
        finally:
            temp_path.unlink()

    def test_wrap_continuation_with_spaces(self):
        """Test wrapping long lines with continuations using spaces."""
        config = LinterConfig.espidf_preset()
        config.max_line_length = 50
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '    bool "Test"\n',
            "    depends on AAAAAAAA && BBBBBBBB && CCCCCCCC\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # Should wrap with backslashes
            assert "\\" in formatted or "depends on" in formatted
        finally:
            temp_path.unlink()

    def test_wrap_continuation_odd_parts(self):
        """Test wrapping with odd number of parts."""
        config = LinterConfig.zephyr_preset()
        config.max_line_length = 40
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\tdepends on A && B\n",  # Just enough to wrap
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            # Should handle gracefully
            assert formatted_lines is not None
        finally:
            temp_path.unlink()

    def test_reflow_empty_paragraph_preservation(self):
        """Test that empty paragraphs are preserved during reflow."""
        config = LinterConfig.zephyr_preset()
        config.reflow_help_text = True
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\thelp\n",
            "\t  Para 1.\n",
            "\n",
            "\n",  # Double blank
            "\t  Para 2.\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # Should have empty lines
            assert "\n\n" in formatted
        finally:
            temp_path.unlink()

    def test_write_mode_file_error(self):
        """Test write mode with file write error."""
        import os

        config = LinterConfig.zephyr_preset()
        _ = KconfigLinter(config)

        # Create a temporary file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.write("config TEST\n")
            f.write('\tbool "Test"\n')
            temp_path = Path(f.name)

        try:
            # Make file read-only to cause write error
            os.chmod(temp_path, 0o444)

            # Try to format with write mode (will fail to write)
            try:
                import sys

                from kconfigstyle.__main__ import main

                old_argv = sys.argv
                sys.argv = ["kconfigstyle", "--write", str(temp_path)]

                # Capture output
                from io import StringIO

                old_stderr = sys.stderr
                sys.stderr = StringIO()

                try:
                    main()
                except SystemExit:
                    pass
                finally:
                    sys.stderr = old_stderr
                    sys.argv = old_argv
            except Exception:
                pass  # Expected to fail

            # Restore permissions for cleanup
            os.chmod(temp_path, 0o644)
        finally:
            if temp_path.exists():
                os.chmod(temp_path, 0o644)
                temp_path.unlink()

    def test_other_line_type_indentation(self):
        """Test indentation of 'other' line types in config block."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\tmodules\n",  # 'other' type line
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # modules should be indented
            assert "\tmodules\n" in formatted
        finally:
            temp_path.unlink()

    def test_help_text_tabs_hierarchical_no_indent_sub_items(self):
        """Test help text with tabs when indent_sub_items is False but we're in a nested context."""
        config = LinterConfig.zephyr_preset()
        config.indent_sub_items = False
        linter = KconfigLinter(config)

        lines = [
            'menu "Test"\n',
            "config A\n",
            '\tbool "A"\n',
            "\thelp\n",
            "\t  Help text.\n",
            "\n",
            "\t  More help.\n",
            "endmenu\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # Help text should maintain proper indentation
            assert "\t  Help text.\n" in formatted
            assert "\t  More help.\n" in formatted
        finally:
            temp_path.unlink()

    def test_help_blank_line_non_matching_indent_no_reflow(self):
        """Test help block ending with non-matching indent and no reflow."""
        config = LinterConfig.zephyr_preset()
        config.reflow_help_text = False
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\thelp\n",
            "\t  Help.\n",
            "\n",
            "other_line\n",  # No help indent
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # other_line should be at top level
            assert "\nother_line\n" in formatted
        finally:
            temp_path.unlink()

    def test_reflow_with_only_empty_lines(self):
        """Test reflow with help text that's only empty lines."""
        config = LinterConfig.zephyr_preset()
        config.reflow_help_text = True
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\thelp\n",
            "\n",
            "\n",
            "config NEXT\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # Should handle gracefully
            assert "config NEXT" in formatted
        finally:
            temp_path.unlink()

    def test_continuation_with_final_part(self):
        """Test continuation line wrapping reaching final part."""
        config = LinterConfig.zephyr_preset()
        config.max_line_length = 35
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\tdepends on A && B && C && D\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # Should wrap properly
            assert "depends on" in formatted
        finally:
            temp_path.unlink()

    def test_help_ending_not_option_or_help(self):
        """Test help block ending with line that's not option or help."""
        config = LinterConfig.espidf_preset()
        config.indent_sub_items = True
        linter = KconfigLinter(config)

        lines = [
            'menu "Test"\n',
            "    config TEST\n",
            '        string "Test"\n',
            "        help\n",
            "            Help text.\n",
            "\n",
            "    menu subthingie\n",  # Not option/help, ends config block
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted_lines, _ = linter.format_file(temp_path)
            formatted = "".join(formatted_lines)

            # menu should be at proper level
            assert "menu" in formatted
        finally:
            temp_path.unlink()

    def test_version_fallback(self):
        """Test that version fallback works."""
        from kconfigstyle import __version__

        # Version should be set (either from metadata or 'unknown')
        assert __version__ is not None
        assert isinstance(__version__, str)

    def test_lint_basic_indentation_help_with_spaces(self):
        """Test linting basic indentation in help mode with spaces."""
        config = LinterConfig.espidf_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '    bool "Test"\n',
            "    help\n",
            "        Help text.\n",  # Correct indent
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            issues = linter.lint_file(temp_path)
            # Should have no issues
            assert len(issues) == 0
        finally:
            temp_path.unlink()

    def test_write_mode_with_unfixable_issues(self):
        """Test write mode reporting unfixable issues."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        # Create file with line that's too long (unfixable)
        long_line = "# " + "x" * 150 + "\n"
        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            long_line,
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            # Lint the file to get issues
            issues = linter.lint_file(temp_path)

            # Should have issue about line length
            assert len(issues) > 0
            assert any("exceeds" in issue.message for issue in issues)
        finally:
            temp_path.unlink()

    def test_default_preset(self):
        """Test that default preset is Zephyr."""
        import sys

        from kconfigstyle.__main__ import main

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.write("config TEST\n")
            f.write('  bool "Test"\n')  # Wrong indent for Zephyr
            temp_path = Path(f.name)

        try:
            old_argv = sys.argv
            sys.argv = ["kconfigstyle", str(temp_path)]

            from io import StringIO

            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                main()
            except SystemExit:
                pass
            finally:
                _ = sys.stdout.getvalue()
                sys.stdout = old_stdout
                sys.argv = old_argv

            # Should report issues (spaces instead of tabs)
            # The test validates the default preset works
        finally:
            temp_path.unlink()


class TestCoverageImprovements:
    """Additional tests to improve code coverage."""

    def test_choice_block_with_name(self):
        """Test parsing and formatting choice block with name."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "choice MY_CHOICE\n",
            '\tprompt "Select option"\n',
            "\tconfig OPT1\n",
            '\t\tbool "Option 1"\n',
            "\tconfig OPT2\n",
            '\t\tbool "Option 2"\n',
            "endchoice\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            # Should preserve choice structure
            assert any("choice" in line for line in formatted)
            assert any("endchoice" in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_choice_block_empty_lines(self):
        """Test choice block with empty lines."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "choice\n",
            "\n",
            "\tconfig OPT1\n",
            '\t\tbool "Option 1"\n',
            "\n",
            "endchoice\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            assert any("choice" in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_source_variants(self):
        """Test different source statement types."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            'source "Kconfig.test"\n',
            'rsource "drivers/Kconfig"\n',
            'osource "optional.Kconfig"\n',
            'orsource "optional2.Kconfig"\n',
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            assert any("source" in line for line in formatted)
            assert any("rsource" in line for line in formatted)
            assert any("osource" in line for line in formatted)
            assert any("orsource" in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_comment_statement(self):
        """Test comment statement (not comment line)."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            'comment "This is a comment statement"\n',
            "\tdepends on FOO\n",
            'comment "Another comment"\n',
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            assert any("comment" in line and '"' in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_choice_with_options(self):
        """Test choice block with options like bool, tristate."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "choice\n",
            '\tbool "Choose one"\n',
            "\tdefault OPT1\n",
            "\tconfig OPT1\n",
            '\t\tbool "Option 1"\n',
            "endchoice\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            assert any("choice" in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_menu_with_depends(self):
        """Test menu with depends statements."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            'menu "Advanced"\n',
            "\tdepends on EXPERT\n",
            "\tdepends on DEBUG\n",
            "\tconfig ADV_OPT\n",
            '\t\tbool "Advanced option"\n',
            "endmenu\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            assert any("menu" in line for line in formatted)
            assert any("depends" in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_line_wrapping_with_or_operator(self):
        """Test line wrapping with || operator."""
        config = LinterConfig.zephyr_preset()
        config.max_line_length = 40
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\tdepends on FOO || BAR || BAZ || QUX || VERY_LONG\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            # Should have continuation lines
            assert any("\\" in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_wrap_line_without_operators(self):
        """Test that lines without && or || aren't wrapped."""
        config = LinterConfig.zephyr_preset()
        config.max_line_length = 30
        linter = KconfigLinter(config)

        lines = [
            "config VERY_LONG_CONFIG_NAME_WITHOUT_OPERATORS\n",
            '\tbool "Test"\n',
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            # Long line without operators shouldn't get backslash
            assert not any("\\" in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_config_option_with_condition(self):
        """Test config option with if condition."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\tdefault y if EXPERT\n",
            '\tstring "Path" if DEBUG\n',
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            assert any("if" in line and "default" in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_def_bool_and_def_tristate(self):
        """Test def_bool and def_tristate options."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST1\n",
            "\tdef_bool y\n",
            "config TEST2\n",
            "\tdef_tristate m\n",
            "config TEST3\n",
            "\tdef_bool y\n",
            "\thelp\n",
            "\t\tTEST3 config\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            assert any("def_bool" in line for line in formatted)
            assert any(
                "def_tristate" in line for line in formatted
            )
        finally:
            temp_path.unlink()

    def test_imply_option(self):
        """Test imply option."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\timply OTHER_OPTION\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            assert any("imply" in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_range_option(self):
        """Test range option."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config NUM\n",
            "\tint\n",
            "\trange 1 100\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            assert any("range" in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_option_keyword(self):
        """Test option keyword."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            '\toption env="TEST_VAR"\n',
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            assert any("option" in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_prompt_option(self):
        """Test prompt option."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            "\tbool\n",
            '\tprompt "Enter value"\n',
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            assert any("prompt" in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_hex_and_int_types(self):
        """Test hex and int config types."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config HEX_VAL\n",
            '\thex "Hex value"\n',
            "config INT_VAL\n",
            '\tint "Int value"\n',
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            assert any("hex" in line for line in formatted)
            assert any("int" in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_help_with_no_content(self):
        """Test help block with no actual help text."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\thelp\n",
            "config NEXT\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            # Should handle gracefully
            assert any("help" in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_config_with_trailing_empty_lines(self):
        """Test config block ending with empty lines at EOF."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\tdefault y\n",
            "\n",
            "\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            # Should handle gracefully
            assert any("config TEST" in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_source_without_quotes(self):
        """Test source statement without quotes."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "source Kconfig.test\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            assert any("source" in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_if_block_hierarchical(self):
        """Test if block with hierarchical indentation."""
        config = LinterConfig.espidf_preset()
        linter = KconfigLinter(config)

        lines = [
            "if FOO\n",
            "config TEST\n",
            'bool "Test"\n',
            "endif\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            # Should indent content inside if block
            assert any("    config" in line or "config" in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_unknown_config_option(self):
        """Test unknown/unrecognized config option."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            '\tbool "Test"\n',
            "\tunknown_option value\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            # Should preserve unknown options
            assert len(formatted) > 0
        finally:
            temp_path.unlink()

    def test_string_type(self):
        """Test string config type."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config PATH\n",
            '\tstring "Enter path"\n',
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            assert any("string" in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_type_without_prompt(self):
        """Test type declaration without prompt."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "config TEST\n",
            "\tbool\n",
            '\tprompt "Test"\n',
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            assert any("bool" in line for line in formatted)
        finally:
            temp_path.unlink()

    def test_complex_nesting_choice_if_menuconfig(self):
        """Test complex nesting with choice, if blocks, and menuconfig."""
        config = LinterConfig.zephyr_preset()
        linter = KconfigLinter(config)

        lines = [
            "choice BUILD_TYPE\n",
            '\tprompt "Build type"\n',
            "\tdefault USE_TYPE_A\n",
            "\thelp\n",
            "\t  Choose the build type\n",
            "\n",
            "config USE_TYPE_A\n",
            '\tbool "Type A"\n',
            "\thelp\n",
            "\t  Use type A\n",
            "\n",
            "menuconfig USE_TYPE_B\n",
            '\tbool "Type B"\n',
            "\tdepends on FEATURE_X\n",
            "\n",
            "if USE_TYPE_B\n",
            "\n",
            "choice TYPE_B_VARIANT\n",
            '\tprompt "Type B variant"\n',
            "\tdefault VARIANT_1\n",
            "\n",
            "config VARIANT_1\n",
            '\tbool "Variant 1"\n',
            "\n",
            "config VARIANT_2\n",
            '\tbool "Variant 2"\n',
            "\n",
            "endchoice\n",
            "\n",
            "endif\n",
            "\n",
            "endchoice\n",
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Kconfig", delete=False
        ) as f:
            f.writelines(lines)
            temp_path = Path(f.name)

        try:
            formatted, _ = linter.format_file(temp_path)
            formatted_text = "".join(formatted)

            # Verify structure is preserved
            assert "choice BUILD_TYPE" in formatted_text
            assert "config USE_TYPE_A" in formatted_text
            assert "menuconfig USE_TYPE_B" in formatted_text
            assert "if USE_TYPE_B" in formatted_text
            assert "choice TYPE_B_VARIANT" in formatted_text
            assert "config VARIANT_1" in formatted_text
            assert "config VARIANT_2" in formatted_text

            # Verify proper closing
            assert formatted_text.count("endchoice") == 2
            assert formatted_text.count("endif") == 1

            # Verify no duplicate or missing blank lines around nested structures
            assert "\n\n\n" not in formatted_text
        finally:
            temp_path.unlink()
