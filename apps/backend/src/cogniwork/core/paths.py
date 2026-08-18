"""定位仓库内的配置文件。

部署时目录结构与仓库不同，所以不写死「往上走 N 层」。
"""

from __future__ import annotations

import os
from pathlib import Path


def find_config_file(filename: str, env_var: str) -> Path:
    override = os.environ.get(env_var)
    if override:
        return Path(override)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "config" / filename
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[5] / "config" / filename
