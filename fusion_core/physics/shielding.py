"""
fusion_core/physics/shielding.py
중성자 방사선 차폐 모델 모듈.

Beer-Lambert 감쇠 모델 기반.
D-T 반응 기준 14.1 MeV 중성자 에너지를 기본 가정.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from fusion_core.contracts.schemas import (
    FusionPhysicsConfig,
    ReactionState,
    ReactionType,
    ShieldingState,
)

# D-T 중성자 에너지 [MeV]
_EN_DT_MEV = 14.1
_EN_DHE3_MEV = 2.45   # D-He3 부반응(D-D) 중성자 에너지
_EN_DD_MEV = 2.45     # D-D 중성자 에너지
_EN_PB11_MEV = 0.0    # p-B11 무중성자 (이론상)


@dataclass
class ShieldingConfig:
    """방사선 차폐 시스템 설정."""

    material_density_kg_m3: float = 11340.0    # 납 밀도                [kg/m³]
    attenuation_coef_m: float = 0.083           # 납 14MeV 중성자 감쇠계수  [m⁻¹] (근사)
    max_dose_rate_sv_hr: float = 0.025          # 최대 허용 선량률       [Sv/hr]
    crew_distance_m: float = 20.0               # 승무원까지 거리        [m]
    shield_area_m2: float = 50.0               # 차폐 면적              [m²]
    dose_factor_sv_per_flux: float = 1.2e-15   # 플럭스→선량 변환      [Sv·m²/n]


class ShieldingModel:
    """중성자 방사선 차폐 계산 모델."""

    def __init__(self, config: ShieldingConfig) -> None:
        self.config = config

    def _neutron_energy_j(self, reaction_type: ReactionType, physics: FusionPhysicsConfig) -> float:
        """반응 유형별 중성자 1개당 에너지 [J]."""
        en_map = {
            ReactionType.DT:   _EN_DT_MEV,
            ReactionType.DHE3: _EN_DHE3_MEV,
            ReactionType.DD:   _EN_DD_MEV,
            ReactionType.PB11: _EN_PB11_MEV,
        }
        en_mev = en_map.get(reaction_type, _EN_DT_MEV)
        return en_mev * physics.mev_to_j

    def neutron_flux(
        self,
        neutron_power_mw: float,
        distance_m: float,
        reaction_type: ReactionType = ReactionType.DT,
        physics: FusionPhysicsConfig | None = None,
    ) -> float:
        """
        중성자 플럭스 [m⁻²s⁻¹].

        Φ = P_n / (4π · r² · E_n_per_neutron)
        """
        if physics is None:
            physics = FusionPhysicsConfig()
        E_n_j = self._neutron_energy_j(reaction_type, physics)
        if E_n_j <= 0.0 or distance_m <= 0.0:
            return 0.0
        P_n_w = neutron_power_mw * 1.0e6
        area = 4.0 * math.pi * (distance_m ** 2)
        return P_n_w / (area * E_n_j)

    def required_thickness_m(self, neutron_flux_val: float) -> float:
        """
        필요 차폐 두께 [m] — Beer-Lambert.

        x = ln(Φ / Φ_threshold) / μ
        Φ_threshold: dose_factor 역산 → max_dose [Sv/hr] 허용 플럭스
        """
        cfg = self.config
        # 허용 플럭스: Φ_limit = max_dose_sv_hr / (dose_factor * 3600)
        dose_sv_per_s = cfg.max_dose_rate_sv_hr / 3600.0
        flux_limit = dose_sv_per_s / cfg.dose_factor_sv_per_flux if cfg.dose_factor_sv_per_flux > 0 else 1e30
        if neutron_flux_val <= flux_limit or flux_limit <= 0:
            return 0.0
        thickness = math.log(neutron_flux_val / flux_limit) / cfg.attenuation_coef_m
        return max(0.0, thickness)

    def required_mass_kg(self, thickness_m: float) -> float:
        """필요 차폐 질량 [kg] = ρ · A · x."""
        return self.config.material_density_kg_m3 * self.config.shield_area_m2 * thickness_m

    def tick(
        self,
        reaction: ReactionState,
        physics: FusionPhysicsConfig,
    ) -> ShieldingState:
        """중성자 출력 → 플럭스 → 선량 → 필요 차폐 질량 계산."""
        cfg = self.config

        flux = self.neutron_flux(
            reaction.power_neutron_mw,
            cfg.crew_distance_m,
            reaction.reaction_type,
            physics,
        )

        # 선량률 [Sv/hr] = flux * dose_factor * 3600
        dose_rate = flux * cfg.dose_factor_sv_per_flux * 3600.0

        thickness = self.required_thickness_m(flux)
        mass = self.required_mass_kg(thickness)

        # 차폐 여유: 1 - dose_rate / max_dose
        margin = 1.0 - (dose_rate / cfg.max_dose_rate_sv_hr) if cfg.max_dose_rate_sv_hr > 0 else 0.0
        margin = max(-1.0, min(1.0, margin))

        return ShieldingState(
            neutron_flux_m2s=flux,
            dose_rate_sv_hr=dose_rate,
            shield_mass_kg=mass,
            shield_thickness_m=thickness,
            margin_fraction=margin,
        )
