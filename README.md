[![](https://img.shields.io/badge/GitHub-noahp/kconfigstyle-8da0cb?style=flat-square&logo=github)](https://github.com/noahp/kconfigstyle)
[![](https://img.shields.io/github/actions/workflow/status/noahp/kconfigstyle/ci.yml?style=flat-square&branch=main)](https://github.com/noahp/kconfigstyle/actions?query=branch%3Amain+)
[![](https://img.shields.io/pypi/v/kconfigstyle?style=flat-square)](https://pypi.org/project/kconfigstyle/)

# ✨ kconfigstyle

A simple style linter + formatter for Kconfig files, with support for Zephyr and
ESP-IDF style conventions.

Example:

```bash
❯ uvx kconfigstyle --write --reflow-help --consolidate-empty-lines --max-line-length 80 Kconfig
```

Before:

```bash
# incorrect and inconsistent indentation, spare newline, and unwrapped help text
config MY_OPTION
  bool "Enable my option" if ANOTHER_OPTION


    help
      Extra long bit of help text that should be reflowed to fit within the maximum line length specified by the style guide.

      This is the second line of the help text.
```

After:

```bash
# properly indented, consolidated newlines, and wrapped help text
config MY_OPTION
	bool "Enable my option" if ANOTHER_OPTION

	help
	  Extra long bit of help text that should be reflowed to fit within the
	  maximum line length specified by the style guide.

	  This is the second line of the help text.
```

## Background

The "Kconfig language" is defined here:

- https://docs.kernel.org/kbuild/kconfig-language.html

There's several extensions used in practice by Zephyr + ESP-IDF; both projects maintain their own forks of the original `kconfiglib` library:

- https://github.com/zephyrproject-rtos/Kconfiglib (actively maintained fork
  used by Zephyr, original library
  [here](https://github.com/ulfalizer/Kconfiglib))

Espressif has an excellent documentation page here about their fork of
Kconfiglib:

- https://docs.espressif.com/projects/esp-idf-kconfig/en/latest/kconfiglib/index.html

Which includes a parser
[here](https://github.com/espressif/esp-idf-kconfig/blob/master/esp_kconfiglib/kconfig_parser.py),
however, that is intended to be used on a complete Kconfig setup, not on a
per-file basis (i.e. it wants to be able to load in sourced files etc). For the
purposes of basic formatting, it's only necessary to parse individual files, so I've
implemented a standalone parser for this use case.

Espressif also provides a tool called
[`kconfcheck`](https://github.com/espressif/esp-idf-kconfig/blob/master/kconfcheck/core.py)
to check Kconfig syntax/formatting, but it is not very configurable and does not
support auto-formatting. `kconfigstyle` aims to provide a more flexible and
user-friendly alternative.

Finally, see here for references on Zephyr and ESP-IDF Kconfig styles:

- https://docs.zephyrproject.org/latest/contribute/style/kconfig.html
- https://docs.espressif.com/projects/esp-idf-kconfig/en/latest/kconfcheck/index.html#kconfig-format-rules

## Installation

Run without installing with `uv`:

```bash
uvx kconfigstyle [options] <kconfig_files>
```

Or install and run:

```bash
pip install kconfigstyle
kconfigstyle [options] <kconfig_files>
```

## Command Line Options

See `kconfigstyle --help` for a full list of options. Some notable options
include:

- `--preset {zephyr,espidf}`
  Use a style preset (individual options override preset values)

- `--write, -w`
  Write formatted output back to files (format mode)

- `--use-spaces`
  Use spaces instead of tabs for indentation

- `--primary-indent PRIMARY_INDENT`
  Number of spaces for primary indentation (default: 4), only applies when
  `--use-spaces` is set

- `--help-indent HELP_INDENT`
  Number of extra spaces for help text indentation (default: 2)

- `--max-line-length MAX_LINE_LENGTH`
  Maximum line length (default: 100 for Zephyr, 120 for ESP-IDF)

- `--max-option-length MAX_OPTION_LENGTH`
  Maximum config option name length (default: 50)

- `--uppercase-configs`
  Require config names to be uppercase

- `--min-prefix-length MIN_PREFIX_LENGTH`
  Minimum prefix length for config names (default: 3 for ESP-IDF)

- `--indent-sub-items`
  Use hierarchical indentation for sub-items (ESP-IDF style)

- `--consolidate-empty-lines`
  Consolidate multiple consecutive empty lines into one

- `--reflow-help`
  Reflow help text to fit within max line length

## License

See LICENSE file for details.
