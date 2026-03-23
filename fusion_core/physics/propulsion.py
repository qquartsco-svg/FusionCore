"""
fusion_core/physics/propulsion.py
핵융합 추진 시스템 물리 모델.

전기추진 모드와 자기노즐 직접추진 모드를 지원.
F = 2P/v_e 관계를 기반으로 추력 계산.
"""

from __future__ import annotations

from dataclasses import dataclass

from fusion_core.contracts.schemas import (
    FusionPhysicsConfig,
    FusionPropulsionState,
    PowerBusState,
    PropulsionMode,
)


@dataclass
class FusionPropulsionConfig:
    """핵융합 추진 시스템 설정."""

    electric_thruster_isp_s: float = 5000.0      # 전기추진기 비추력     [s]
    electric_efficiency: float = 0.65             # 전력→추력 효율       [무차원]
    magnetic_nozzle_efficiency: float = 0.60      # 자기노즐 직접추진 효율 [무차원]
    min_power_for_thrust_mw: float = 1.0          # 최소 추진 가능 전력   [MW]


class FusionPropulsionEngine:
    """핵융합 추진 엔진 물리 계산기."""

    def __init__(self, config: FusionPropulsionConfig) -> None:
        self.config = config

    def electric_mode(
        self,
        thrust_power_mw: float,
        physics: FusionPhysicsConfig,
    ) -> FusionPropulsionState:
        """
        전기추진 모드 계산.

        v_e = Isp * g0
        P_eff = P * efficiency
        F = 2 * P_eff / v_e
        mdot = F / v_e
        """
        cfg = self.config
        v_e = cfg.electric_thruster_isp_s * physics.g0  # [m/s]
        if thrust_power_mw < cfg.min_power_for_thrust_mw or v_e <= 0.0:
            return FusionPropulsionState(
                thrust_n=0.0,
                isp_s=cfg.electric_thruster_isp_s,
                exhaust_vel_ms=v_e,
                mass_flow_kgs=0.0,
                power_to_thrust_efficiency=cfg.electric_efficiency,
                mode=PropulsionMode.ELECTRIC_ONLY,
            )
        P_eff_w = thrust_power_mw * 1.0e6 * cfg.electric_efficiency
        thrust_n = 2.0 * P_eff_w / v_e
        mdot = thrust_n / v_e
        return FusionPropulsionState(
            thrust_n=thrust_n,
            isp_s=cfg.electric_thruster_isp_s,
            exhaust_vel_ms=v_e,
            mass_flow_kgs=mdot,
            power_to_thrust_efficiency=cfg.electric_efficiency,
            mode=PropulsionMode.ELECTRIC_ONLY,
        )

    def direct_mode(
        self,
        charged_power_mw: float,
        physics: FusionPhysicsConfig,
    ) -> FusionPropulsionState:
        """
        직접 추진 모드 (자기노즐) 계산.

        Isp 추정: 자기노즐 Isp ~ 10000~50000s (중간값 사용)
        F = 2 * P_charged * efficiency / v_e
        """
        cfg = self.config
        # 자기노즐 Isp 추정 [s] — 하전입자 에너지에서 추산
        # 핵융합 하전입자(알파, 약 3.5 MeV) 기준 속도: ~1.3e7 m/s
        # 자기노즐은 이보다 낮은 Isp로 실현 (실용적 효율 고려)
        isp_estimate_s = 20000.0  # 자기노즐 중간 추정값 [s]
        v_e = isp_estimate_s * physics.g0

        if charged_power_mw < cfg.min_power_for_thrust_mw or v_e <= 0.0:
            return FusionPropulsionState(
                thrust_n=0.0,
                isp_s=isp_estimate_s,
                exhaust_vel_ms=v_e,
                mass_flow_kgs=0.0,
                power_to_thrust_efficiency=cfg.magnetic_nozzle_efficiency,
                mode=PropulsionMode.DIRECT_THRUST,
            )

        P_eff_w = charged_power_mw * 1.0e6 * cfg.magnetic_nozzle_efficiency
        thrust_n = 2.0 * P_eff_w / v_e
        mdot = thrust_n / v_e if v_e > 0.0 else 0.0

        return FusionPropulsionState(
            thrust_n=thrust_n,
            isp_s=isp_estimate_s,
            exhaust_vel_ms=v_e,
            mass_flow_kgs=mdot,
            power_to_thrust_efficiency=cfg.magnetic_nozzle_efficiency,
            mode=PropulsionMode.DIRECT_THRUST,
        )

    def tick(
        self,
        power_bus: PowerBusState,
        physics: FusionPhysicsConfig,
    ) -> FusionPropulsionState:
        """추진 모드에 따라 electric_mode 또는 direct_mode 호출."""
        mode = power_bus.mode
        if mode == PropulsionMode.OFF:
            cfg = self.config
            v_e = cfg.electric_thruster_isp_s * physics.g0
            return FusionPropulsionState(
                thrust_n=0.0,
                isp_s=cfg.electric_thruster_isp_s,
                exhaust_vel_ms=v_e,
                mass_flow_kgs=0.0,
                power_to_thrust_efficiency=0.0,
                mode=PropulsionMode.OFF,
            )
        elif mode == PropulsionMode.ELECTRIC_ONLY:
            return self.electric_mode(power_bus.thrust_mw, physics)
        elif mode == PropulsionMode.DIRECT_THRUST:
            return self.direct_mode(power_bus.thrust_mw, physics)
        elif mode == PropulsionMode.HYBRID:
            # 전기 + 직접 추진 혼합: 전력을 반반 분배
            half_mw = power_bus.thrust_mw / 2.0
            e_state = self.electric_mode(half_mw, physics)
            d_state = self.direct_mode(half_mw, physics)
            total_thrust = e_state.thrust_n + d_state.thrust_n
            total_mdot = e_state.mass_flow_kgs + d_state.mass_flow_kgs
            # 유효 Isp = F / (mdot * g0)
            eff_isp = (total_thrust / (total_mdot * physics.g0)) if total_mdot > 0 else 0.0
            avg_eff = (e_state.power_to_thrust_efficiency + d_state.power_to_thrust_efficiency) / 2.0
            return FusionPropulsionState(
                thrust_n=total_thrust,
                isp_s=eff_isp,
                exhaust_vel_ms=eff_isp * physics.g0,
                mass_flow_kgs=total_mdot,
                power_to_thrust_efficiency=avg_eff,
                mode=PropulsionMode.HYBRID,
            )
        # 기본 — OFF
        return self.tick(
            power_bus.__class__(
                **{**power_bus.__dict__, "mode": PropulsionMode.OFF}
            ),
            physics,
        )
