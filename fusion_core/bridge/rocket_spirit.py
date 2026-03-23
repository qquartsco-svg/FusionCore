"""
fusion_core/bridge/rocket_spirit.py
FusionCore ↔ Rocket_Spirit 브릿지 모듈.

Rocket_Spirit이 설치된 환경에서는 실제 TelemetryFrame을 변환하고,
미설치 환경에서는 dict 기반 호환 인터페이스를 제공한다.
"""

from __future__ import annotations

try:
    from launch_vehicle.contracts.schemas import TelemetryFrame as RSFrame
    ROCKET_SPIRIT_AVAILABLE = True
except ImportError:
    ROCKET_SPIRIT_AVAILABLE = False
    RSFrame = None  # type: ignore[assignment,misc]

from fusion_core.contracts.schemas import FusionCoreState


def bridge_fusion_to_rocket(fusion_state: FusionCoreState) -> dict:
    """
    FusionCore 추진 출력 → Rocket_Spirit PropulsionState 호환 dict.

    반환 형식:
        {
            "thrust_n":      float,   # 추력 [N]
            "isp_s":         float,   # 비추력 [s]
            "mass_flow_kgs": float,   # 추진제 유량 [kg/s]
            "is_ignited":    bool,    # 핵융합 점화 여부
        }
    """
    from fusion_core.contracts.schemas import PlasmaPhase

    is_ignited = fusion_state.plasma.phase in (
        PlasmaPhase.BURNING,
        PlasmaPhase.HIGH_Q_BURN,
    )
    return {
        "thrust_n":      fusion_state.propulsion.thrust_n,
        "isp_s":         fusion_state.propulsion.isp_s,
        "mass_flow_kgs": fusion_state.propulsion.mass_flow_kgs,
        "is_ignited":    is_ignited,
        "power_total_mw": fusion_state.reaction.power_total_mw,
        "reaction_type": fusion_state.reaction.reaction_type.value,
    }


def bridge_rocket_to_fusion(rs_frame: dict) -> dict:
    """
    Rocket_Spirit telemetry → FusionCore 입력 파라미터.

    rs_frame 예상 키:
        altitude_m, speed_ms, dynamic_q_pa

    반환 형식:
        {
            "altitude_m":     float,  # 고도 [m]
            "speed_ms":       float,  # 속도 [m/s]
            "dynamic_q_pa":   float,  # 동압 [Pa]
        }
    열 방출 환경 파라미터로 활용 가능.
    """
    return {
        "altitude_m":   float(rs_frame.get("altitude_m", 0.0)),
        "speed_ms":     float(rs_frame.get("speed_ms", 0.0)),
        "dynamic_q_pa": float(rs_frame.get("dynamic_q_pa", 0.0)),
    }
