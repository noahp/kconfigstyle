[![](https://img.shields.io/badge/GitHub-noahp/kconfstyle-8da0cb?style=flat-square&logo=github)](https://github.com/noahp/kconfstyle)
[![](https://img.shields.io/github/actions/workflow/status/noahp/kconfstyle/ci.yml?style=flat-square&branch=main)](https://github.com/noahp/kconfstyle/actions?query=branch%3Amain+)
[![](https://img.shields.io/pypi/v/kconfstyle?style=flat-square)](https://pypi.org/project/kconfstyle/)

> **NOTE** this package has been renamed from `kconfstyle` to `kconfigstyle`!
> This package will no longer receive updates.

# kconfstyle

A simple linter for Kconfig files, with support for Zephyr and ESP-IDF coding
styles.

See here for refences on Zephyr and ESP-IDF Kconfig styles:

- https://docs.zephyrproject.org/latest/contribute/style/kconfig.html
- https://docs.espressif.com/projects/esp-idf-kconfig/en/latest/kconfcheck/index.html#kconfig-format-rules

Espressif provides a tool called
[`kconfcheck`](https://github.com/espressif/esp-idf-kconfig/blob/master/kconfcheck/core.py)
to check Kconfig formatting, but it is not very configurable and does not
support auto-formatting. `kconfstyle` aims to provide a more flexible and
user-friendly alternative.

## Installation

Run without installing with `uv`:

```bash
uvx kconfstyle [options] <kconfig_files>
```

Or install and run:

```bash
pip install kconfstyle
kconfstyle [options] <kconfig_files>
```

## License

See LICENSE file for details.
