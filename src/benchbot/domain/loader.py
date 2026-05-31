"""Parse protocols from YAML/JSON text or files into :class:`Protocol`.

Two step spellings are accepted and normalized to the same model:

* explicit:  ``{type: transfer, source: ..., dest: ..., volume_ul: 100}``
* shorthand: ``{transfer: {source: ..., dest: ..., volume_ul: 100}}``
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from benchbot.domain.protocol import Protocol

_STEP_TYPES = {"transfer", "aspirate", "dispense", "mix"}


def _normalize_step(raw: Any) -> Any:
    """Expand the ``{<type>: {...}}`` shorthand into ``{type: <type>, ...}``."""
    if isinstance(raw, dict) and "type" not in raw and len(raw) == 1:
        (key,) = raw
        if key in _STEP_TYPES:
            body = raw[key] or {}
            if not isinstance(body, dict):
                raise ValueError(f"step '{key}' must map to an object, got {type(body).__name__}")
            return {"type": key, **body}
    return raw


def _normalize(data: Any) -> Any:
    if not isinstance(data, dict):
        raise ValueError("protocol must be a mapping at the top level")
    steps = data.get("steps")
    if isinstance(steps, list):
        data = {**data, "steps": [_normalize_step(s) for s in steps]}
    return data


def load_protocol_text(text: str) -> Protocol:
    """Parse a protocol from a YAML or JSON string."""
    data = yaml.safe_load(text)
    return Protocol.model_validate(_normalize(data))


def load_protocol_file(path: str | Path) -> Protocol:
    """Parse a protocol from a ``.yaml``/``.yml``/``.json`` file."""
    return load_protocol_text(Path(path).read_text(encoding="utf-8"))
