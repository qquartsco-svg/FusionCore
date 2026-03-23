"""Public API smoke tests for FusionCore_Stack."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fusion_core import (  # noqa: E402
    AbortMode,
    FusionAgent,
    FusionAgentConfig,
    FusionChain,
    FusionPhysicsConfig,
    PlasmaPhase,
    ReactionType,
    __version__,
)


def test_root_exports_version():
    assert __version__ == "0.1.0"


def test_root_exports_core_types():
    assert FusionAgent is not None
    assert FusionChain is not None
    assert FusionPhysicsConfig is not None
    assert PlasmaPhase.COLD.value == "COLD"
    assert ReactionType.DT.value == "D-T"
    assert AbortMode.NONE.value == "NONE"


def test_root_agent_construction():
    agent = FusionAgent(FusionAgentConfig())
    frame = agent.tick()
    assert frame.phase in PlasmaPhase
