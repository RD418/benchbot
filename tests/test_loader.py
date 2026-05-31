from __future__ import annotations

from pathlib import Path

import pytest

from benchbot.domain.loader import load_protocol_file, load_protocol_text
from benchbot.domain.protocol import MixStep, TransferStep

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_shorthand_and_explicit_steps_are_equivalent() -> None:
    shorthand = load_protocol_text(
        """
        version: 1
        steps:
          - transfer: { source: "p:A1", dest: "p:A2", volume_ul: 10 }
        """
    )
    explicit = load_protocol_text(
        """
        version: 1
        steps:
          - { type: transfer, source: "p:A1", dest: "p:A2", volume_ul: 10 }
        """
    )
    assert shorthand.steps == explicit.steps


def test_discriminated_union_picks_right_step_type() -> None:
    protocol = load_protocol_text(
        """
        version: 1
        steps:
          - transfer: { source: "p:A1", dest: "p:A2", volume_ul: 10 }
          - mix: { well: "p:A2", volume_ul: 5, repeats: 2 }
        """
    )
    assert isinstance(protocol.steps[0], TransferStep)
    assert isinstance(protocol.steps[1], MixStep)
    assert protocol.steps[1].repeats == 2


def test_example_files_parse() -> None:
    assert load_protocol_file(EXAMPLES / "serial_dilution.yaml").metadata.name == "Serial dilution"
    # The invalid example must still *parse* — it fails validation, not loading.
    assert load_protocol_file(EXAMPLES / "invalid_protocol.yaml") is not None


def test_bad_shorthand_body_raises() -> None:
    with pytest.raises(ValueError):
        load_protocol_text(
            """
            version: 1
            steps:
              - transfer: "not-an-object"
            """
        )


def test_non_mapping_top_level_raises() -> None:
    with pytest.raises(ValueError):
        load_protocol_text("- just\n- a\n- list")
