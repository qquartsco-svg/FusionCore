"""
fusion_core/safety/omega_monitor.py
핵융합 코어 종합 건전성(Ω) 모니터.

각 서브시스템별 건전성 지표를 [0,1]로 정규화하고 가중합산하여
종합 건전성 Ω_fusion을 산출한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from fusion_core.contracts.schemas import (
    FusionCoreState,
    FusionHealth,
    PlasmaPhase,
)


@dataclass
class OmegaConfig:
    """건전성 가중치 설정."""

    w_plasma: float = 0.30
    w_thermal: float = 0.25
    w_shielding: float = 0.20
    w_fuel: float = 0.15
    w_power: float = 0.10

    # 참조 전력 수요 [MW] (전력 건전성 분모)
    base_electric_demand_mw: float = 50.0


class OmegaMonitor:
    """핵융합 코어 종합 건전성 관측기."""

    def observe(
        self,
        state: FusionCoreState,
        config: OmegaConfig,
    ) -> FusionHealth:
        """
        각 서브시스템 건전성을 [0,1]로 계산하고 가중합산.

        Ω_plasma   : q_factor, triple_product, beta 여유 기반
        Ω_thermal  : thermal_margin 기반
        Ω_shielding: 차폐 여유 기반
        Ω_fuel     : 잔여 연료 기반
        Ω_power    : 전기 공급 / 기본 수요 기반
        """
        alerts: list[str] = []

        # --- Ω_plasma ---
        plasma = state.plasma
        # Q 인자: Q >= 1 → healthy (자립 연소)
        q_score = min(1.0, plasma.q_factor / 5.0) if plasma.q_factor >= 0 else 0.0
        # 베타 여유: (max_beta - beta) / max_beta. max_beta = 0.1로 가정
        max_beta_ref = 0.10
        beta_margin = (max_beta_ref - plasma.beta) / max_beta_ref
        beta_score = max(0.0, min(1.0, beta_margin))
        # 온도 기여 (점화 온도 4 keV 대비)
        temp_score = min(1.0, plasma.temperature_kev / 20.0)

        # 위상 가산점
        phase_score = {
            PlasmaPhase.COLD:             0.1,
            PlasmaPhase.PREHEATING:       0.3,
            PlasmaPhase.IGNITION_ATTEMPT: 0.5,
            PlasmaPhase.BURNING:          0.8,
            PlasmaPhase.SUSTAINED:        1.0,
            PlasmaPhase.QUENCH:           0.0,
            PlasmaPhase.SHUTDOWN:         0.0,
        }.get(plasma.phase, 0.0)

        omega_plasma = (q_score * 0.4 + beta_score * 0.3 + temp_score * 0.15 + phase_score * 0.15)
        omega_plasma = max(0.0, min(1.0, omega_plasma))

        if plasma.beta > 0.08:
            alerts.append(f"HIGH_BETA: beta={plasma.beta:.4f}")
        if plasma.q_factor < 1.0 and plasma.phase in (PlasmaPhase.BURNING, PlasmaPhase.SUSTAINED):
            alerts.append(f"LOW_Q_FACTOR: Q={plasma.q_factor:.2f}")

        # --- Ω_thermal ---
        omega_thermal = max(0.0, min(1.0, state.thermal.thermal_margin))
        if state.thermal.thermal_margin < 0.10:
            alerts.append(f"THERMAL_CRITICAL: margin={state.thermal.thermal_margin:.3f}")

        # --- Ω_shielding ---
        omega_shielding = max(0.0, min(1.0, state.shielding.margin_fraction))
        if state.shielding.margin_fraction < 0.10:
            alerts.append(f"SHIELDING_CRITICAL: margin={state.shielding.margin_fraction:.3f}")

        # --- Ω_fuel ---
        omega_fuel = max(0.0, min(1.0, state.fuel.remaining_fraction()))
        if state.fuel.remaining_fraction() < 0.10:
            alerts.append(f"LOW_FUEL: remaining={state.fuel.remaining_fraction():.3f}")

        # --- Ω_power ---
        demand = config.base_electric_demand_mw
        supply = state.power_bus.electric_mw
        omega_power = min(1.0, supply / demand) if demand > 0 else 1.0
        omega_power = max(0.0, omega_power)
        if omega_power < 0.5:
            alerts.append(f"LOW_POWER: supply={supply:.1f}MW / demand={demand:.1f}MW")

        # --- Ω_fusion 가중합 ---
        cfg = config
        omega_fusion = (
            cfg.w_plasma    * omega_plasma
            + cfg.w_thermal   * omega_thermal
            + cfg.w_shielding * omega_shielding
            + cfg.w_fuel      * omega_fuel
            + cfg.w_power     * omega_power
        )
        omega_fusion = max(0.0, min(1.0, omega_fusion))

        # 판정
        if omega_fusion > 0.8:
            verdict = "HEALTHY"
        elif omega_fusion > 0.6:
            verdict = "STABLE"
        elif omega_fusion > 0.4:
            verdict = "FRAGILE"
        else:
            verdict = "CRITICAL"

        abort_required = (
            omega_fusion < 0.25
            or plasma.beta > 0.10
            or state.shielding.dose_rate_sv_hr > 0.1
            or state.thermal.thermal_margin < 0.05
        )
        if abort_required:
            alerts.append("ABORT_RECOMMENDED")

        return FusionHealth(
            omega_fusion=omega_fusion,
            omega_plasma=omega_plasma,
            omega_thermal=omega_thermal,
            omega_shielding=omega_shielding,
            omega_fuel=omega_fuel,
            omega_power=omega_power,
            verdict=verdict,
            alerts=tuple(alerts),
            abort_required=abort_required,
        )
