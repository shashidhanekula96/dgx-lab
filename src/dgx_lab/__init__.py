# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""dgx-lab — multi-OS config-as-code comparison lab for OpenAI-compatible runtimes."""

__version__ = "0.1.0"

AUTHOR = "Shashikanth Dhanekula"
SPDX_LICENSE = "MIT"
COPYRIGHT = "Copyright (c) 2026 Shashikanth Dhanekula"

DATA_ROOT_ENV = "DGX_LAB_ROOT"
DEFAULT_DATA_ROOT_NAME = "dgx-lab"
OPERATOR_ENV = "DGX_LAB_OPERATOR"
API_TOKEN_ENV = "DGX_LAB_API_TOKEN"


def credits() -> str:
    """Return the mandatory project credits / signature block."""
    return (
        f"dgx-lab {__version__}\n"
        f"{COPYRIGHT}\n"
        f"Author: {AUTHOR}\n"
        f"License: {SPDX_LICENSE} (SPDX-License-Identifier: {SPDX_LICENSE})\n"
    )
