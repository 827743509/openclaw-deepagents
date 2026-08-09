from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from ssw.schemas.mcp import McpConfig


class McpRepository:
    MAX_CONFIG_SIZE = 1024 * 1024

    def __init__(self, project_root: Path) -> None:
        self.config_path = project_root.resolve() / "mcp.json"

    def get(self) -> McpConfig:
        if not self.config_path.exists():
            return McpConfig()

        if self.config_path.stat().st_size > self.MAX_CONFIG_SIZE:
            raise ValueError("mcp.json 不能超过 1 MB")

        try:
            raw_config = json.loads(self.config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"mcp.json 格式错误：{exc.msg}") from exc
        return McpConfig.model_validate(raw_config)

    def save(self, config: McpConfig) -> McpConfig:
        content = json.dumps(
            config.model_dump(
                by_alias=True,
                exclude_none=True,
                exclude_defaults=True,
            ),
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        if len(content.encode("utf-8")) > self.MAX_CONFIG_SIZE:
            raise ValueError("mcp.json 不能超过 1 MB")

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.config_path.parent,
                prefix=".mcp-",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_file.write(content)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_path = temp_file.name
            os.replace(temp_path, self.config_path)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
        return config
