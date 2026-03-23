"""
fusion_core/bridge/brain_core.py
FusionCore ↔ BrainCore 브릿지 모듈.

BrainCore(cookiie_brain)가 설치된 환경에서는 MemoryWell을 통해
상태를 메모리에 주입하고 명령을 수신한다.
미설치 환경에서는 dict 기반 호환 인터페이스를 제공한다.
"""

from __future__ import annotations

from typing import Tuple

try:
    from cookiie_brain import MemoryWell
    BRAIN_AVAILABLE = True
except ImportError:
    BRAIN_AVAILABLE = False
    MemoryWell = None  # type: ignore[assignment,misc]

from fusion_core.contracts.schemas import (
    FusionCoreState,
    FusionHealth,
    PropulsionMode,
)


def fusion_state_to_memory(
    state: FusionCoreState,
    health: FusionHealth,
) -> dict:
    """
    FusionCore 상태 → BrainCore 메모리 주입 포맷.

    반환 형식은 BrainCore MemoryWell.inject() 호환 dict.
    """
    return {
        "source": "FusionCore",
        "t_s": state.t_s,
        "omega_fusion": health.omega_fusion,
        "verdict": health.verdict,
        "abort_required": health.abort_required,
        "alerts": list(health.alerts),
        "plasma": {
            "temperature_kev": state.plasma.temperature_kev,
            "phase": state.plasma.phase.value,
            "q_factor": state.plasma.q_factor,
            "beta": state.plasma.beta,
        },
        "reaction": {
            "power_total_mw": state.reaction.power_total_mw,
            "power_charged_mw": state.reaction.power_charged_mw,
            "reaction_type": state.reaction.reaction_type.value,
        },
        "propulsion": {
            "thrust_n": state.propulsion.thrust_n,
            "isp_s": state.propulsion.isp_s,
            "mode": state.propulsion.mode.value,
        },
        "fuel_remaining": state.fuel.remaining_fraction(),
    }


def brain_command_to_fusion(cmd: dict) -> Tuple[PropulsionMode, float, bool]:
    """
    BrainCore 명령 → (PropulsionMode, throttle, go_command).

    cmd 예상 키:
        propulsion_mode: str    (PropulsionMode 값)
        throttle:        float  [0, 1]
        go_command:      bool
    """
    mode_str = cmd.get("propulsion_mode", "OFF")
    try:
        mode = PropulsionMode(mode_str)
    except ValueError:
        mode = PropulsionMode.OFF

    throttle = float(cmd.get("throttle", 0.0))
    throttle = max(0.0, min(1.0, throttle))

    go_command = bool(cmd.get("go_command", False))

    return mode, throttle, go_command
