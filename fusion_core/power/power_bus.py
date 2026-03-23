"""
fusion_core/power/power_bus.py
핵융합 코어 전력 버스 관리 모듈.

하전입자 출력만 전기로 변환 가능하다는 물리 제약을 반영.
추진 모드에 따라 전기·열관리·추진에 전력을 배분한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from fusion_core.contracts.schemas import (
    PowerBusState,
    PropulsionMode,
    ReactionState,
)


@dataclass
class PowerBusConfig:
    """전력 버스 설정."""

    base_electric_mw: float = 50.0         # 기본 전기 부하 (생명유지·항법)  [MW]
    thermal_mgmt_fraction: float = 0.05    # 열관리 배분 비율
    thrust_priority: float = 0.80          # 추진 우선 배분 비율
    parasitic_loss_fraction: float = 0.03  # 기생 손실 비율
    min_electric_mw: float = 10.0          # 최소 전기 보장량               [MW]


class PowerBusController:
    """핵융합 전력 버스 배분 컨트롤러."""

    def allocate(
        self,
        reaction: ReactionState,
        demand_mode: PropulsionMode,
        config: PowerBusConfig,
    ) -> PowerBusState:
        """
        가용 전력 = reaction.power_charged_mw (하전입자 전력만 전환 가능).

        배분 순서:
        1. 기생 손실 차감
        2. 최소 전기 보장
        3. 열관리 배분
        4. 나머지: mode에 따라 thrust vs electric 분배
        """
        cfg = config
        total_available = reaction.power_charged_mw

        # 1. 기생 손실
        parasitic_mw = total_available * cfg.parasitic_loss_fraction
        after_parasitic = total_available - parasitic_mw

        # 2. 열관리 배분
        thermal_mgmt_mw = after_parasitic * cfg.thermal_mgmt_fraction
        after_thermal = after_parasitic - thermal_mgmt_mw

        # 3. 최소 전기 보장 (생명유지·항법)
        electric_base = min(cfg.min_electric_mw, after_thermal)
        after_base = after_thermal - electric_base

        if demand_mode == PropulsionMode.OFF:
            # 추진 없음: 남은 전력 모두 전기계통
            thrust_mw = 0.0
            electric_mw = electric_base + after_base
        elif demand_mode == PropulsionMode.ELECTRIC_ONLY:
            # 기본 전기 + 가용분 중 thrust_priority는 전기추진, 나머지 일반전기
            thrust_mw = after_base * cfg.thrust_priority
            electric_mw = electric_base + after_base * (1.0 - cfg.thrust_priority)
        elif demand_mode == PropulsionMode.DIRECT_THRUST:
            # 직접 추진 우선
            thrust_mw = after_base * cfg.thrust_priority
            electric_mw = electric_base + after_base * (1.0 - cfg.thrust_priority)
        elif demand_mode == PropulsionMode.HYBRID:
            # 혼합: thrust_priority 비율 추진, 나머지 전기
            thrust_mw = after_base * cfg.thrust_priority
            electric_mw = electric_base + after_base * (1.0 - cfg.thrust_priority)
        else:
            thrust_mw = 0.0
            electric_mw = electric_base + after_base

        # 효율 = (전기 + 추진) / 가용
        useful = electric_mw + thrust_mw + thermal_mgmt_mw
        efficiency = useful / total_available if total_available > 0.0 else 0.0
        efficiency = max(0.0, min(1.0, efficiency))

        return PowerBusState(
            total_available_mw=total_available,
            electric_mw=max(0.0, electric_mw),
            thrust_mw=max(0.0, thrust_mw),
            thermal_mgmt_mw=max(0.0, thermal_mgmt_mw),
            parasitic_mw=max(0.0, parasitic_mw),
            allocation_efficiency=efficiency,
            mode=demand_mode,
        )
