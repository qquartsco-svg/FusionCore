"""
fusion_core/plasma/confinement.py
플라즈마 가둠(Confinement) 물리 모델.

로손 기준, 베타 파라미터, Q 인자 추정 등 플라즈마 물리 평가.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from fusion_core.contracts.schemas import (
    FusionPhysicsConfig,
    PlasmaPhase,
    PlasmaState,
    ReactionType,
)


@dataclass
class ConfinementConfig:
    """플라즈마 가둠 시스템 설정."""

    dt_lawson_threshold: float = 3.0e21    # D-T 로손 기준 nτT   [keV·s/m³]
    dhe3_lawson_threshold: float = 1.0e23  # D-He3 로손 기준     [keV·s/m³]
    b_field_tesla: float = 5.0             # 자기장 강도          [T]
    max_beta: float = 0.05                 # 최대 안전 베타 (토카막)
    energy_confinement_time_s: float = 3.0 # 에너지 가둠 시간     [s]


# 진공 투자율 μ₀
_MU_0 = 4.0 * math.pi * 1.0e-7  # H/m


class ConfinementModel:
    """플라즈마 가둠 물리 평가 모델."""

    def __init__(self, config: ConfinementConfig) -> None:
        self.config = config

    def triple_product(self, plasma: PlasmaState) -> float:
        """nτT [keV·s/m³] = density · confinement_time · temperature_kev."""
        return plasma.density_m3 * plasma.confinement_time_s * plasma.temperature_kev

    def lawson_satisfied(
        self,
        plasma: PlasmaState,
        reaction_type: ReactionType,
    ) -> bool:
        """triple_product > 로손 기준 여부."""
        tp = self.triple_product(plasma)
        threshold = {
            ReactionType.DT:   self.config.dt_lawson_threshold,
            ReactionType.DHE3: self.config.dhe3_lawson_threshold,
            ReactionType.DD:   self.config.dt_lawson_threshold * 10.0,
            ReactionType.PB11: self.config.dhe3_lawson_threshold * 10.0,
        }.get(reaction_type, self.config.dt_lawson_threshold)
        return tp >= threshold

    def q_factor_estimate(
        self,
        plasma: PlasmaState,
        heating_power_mw: float,
    ) -> float:
        """
        Q 인자 추정 = P_fusion / P_heat.

        P_heat ≠ 0일 때만 계산. 플라즈마 압력·가둠 기반 추산.
        """
        if heating_power_mw <= 0.0:
            return 0.0
        # Q ∝ triple_product / Lawson_threshold (단순 선형 추산)
        tp = self.triple_product(plasma)
        tp_norm = tp / self.config.dt_lawson_threshold  # 정규화
        # 알파 자가 가열 포함 추정: Q ≈ 5 * (tp_norm - 1) 근사
        q_est = max(0.0, 5.0 * (tp_norm - 1.0))
        return q_est

    def beta_estimate(
        self,
        plasma: PlasmaState,
        physics: FusionPhysicsConfig,
    ) -> float:
        """
        β = n·k_B·T / (B²/2μ₀).

        플라즈마 압력 / 자기 압력.
        """
        T_j = plasma.temperature_kev * physics.kev_to_j
        # 이온 + 전자 (n_total = 2 * n_ion 근사, 완전 이온화)
        n_total = 2.0 * plasma.density_m3
        p_plasma = n_total * physics.k_b * (T_j / physics.k_b)  # = n_total * T_j
        B = self.config.b_field_tesla
        p_magnetic = (B ** 2) / (2.0 * _MU_0)
        if p_magnetic <= 0.0:
            return 0.0
        return min(1.0, p_plasma / p_magnetic)

    def assess(
        self,
        plasma: PlasmaState,
        reaction_type: ReactionType,
        heating_power_mw: float,
        physics: FusionPhysicsConfig | None = None,
    ) -> PlasmaState:
        """
        triple_product, q_factor, beta, lawson 상태를 갱신한 PlasmaState 반환.
        """
        if physics is None:
            physics = FusionPhysicsConfig()

        tp = self.triple_product(plasma)
        q = self.q_factor_estimate(plasma, heating_power_mw)
        beta = self.beta_estimate(plasma, physics)

        return PlasmaState(
            temperature_kev=plasma.temperature_kev,
            density_m3=plasma.density_m3,
            confinement_time_s=plasma.confinement_time_s,
            beta=beta,
            q_factor=q,
            triple_product=tp,
            heating_power_mw=heating_power_mw,
            phase=plasma.phase,
        )
