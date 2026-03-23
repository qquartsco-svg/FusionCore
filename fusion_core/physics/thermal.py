"""
fusion_core/physics/thermal.py
핵융합 반응로 열 관리 시스템 모듈.

방열판 복사 모델(스테판-볼츠만) + 냉각계 열용량 기반 온도 적분.
모든 물리 상수는 FusionPhysicsConfig에서 주입받는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from fusion_core.contracts.schemas import FusionPhysicsConfig, ThermalState


@dataclass
class ThermalConfig:
    """열 관리 시스템 설정."""

    radiator_area_m2: float = 5000.0             # 방열판 면적             [m²]
    emissivity: float = 0.9                       # 방열판 방사율           [무차원]
    specific_mass_kg_m2: float = 10.0             # 비질량                  [kg/m²]
    max_core_temp_k: float = 2000.0               # 코어 최대 허용 온도     [K]
    coolant_heat_capacity_j_per_k: float = 1.0e8  # 냉각계 열용량           [J/K]
    initial_radiator_temp_k: float = 900.0        # 초기 방열판 온도        [K]


class ThermalSystem:
    """핵융합 반응로 열 관리 시스템."""

    def __init__(self, config: ThermalConfig) -> None:
        self.config = config

    def radiated_power_mw(self, T_rad_k: float) -> float:
        """방열판 복사 출력 [MW] = ε · σ · A · T⁴."""
        cfg = self.config
        # 단위: W → MW
        power_w = cfg.emissivity * 5.670374419e-8 * cfg.radiator_area_m2 * (T_rad_k ** 4)
        return power_w * 1.0e-6

    def tick(
        self,
        heat_load_mw: float,
        dt_s: float,
        state: ThermalState,
        physics: FusionPhysicsConfig,
    ) -> ThermalState:
        """
        방열판 온도 적분 (오일러 1차).

        dT_rad/dt = (Q_in - Q_out) / C_thermal
        thermal_margin = (T_max - T_core) / T_max
        """
        cfg = self.config

        # 현재 방열판 복사 출력 [MW]
        P_rad_mw = self.radiated_power_mw(state.radiator_temp_k)

        # 열 부하 - 방열: [MW]
        net_mw = heat_load_mw - P_rad_mw

        # 온도 변화율 dT/dt [K/s]
        # C_thermal [J/K], net [MW] = net * 1e6 [W]
        dT_dt = (net_mw * 1.0e6) / cfg.coolant_heat_capacity_j_per_k

        new_rad_temp_k = max(3.0, state.radiator_temp_k + dT_dt * dt_s)

        # 코어 온도 추정: 방열판 온도 + 냉각 온도차 근사 (열저항 1e-4 K/W)
        thermal_resistance_k_per_w = 1.0e-7  # [K/W]
        delta_t_k = heat_load_mw * 1.0e6 * thermal_resistance_k_per_w
        new_core_temp_k = new_rad_temp_k + delta_t_k
        new_coolant_temp_k = (new_core_temp_k + new_rad_temp_k) / 2.0

        thermal_margin = (cfg.max_core_temp_k - new_core_temp_k) / cfg.max_core_temp_k
        thermal_margin = max(-1.0, min(1.0, thermal_margin))

        return ThermalState(
            core_temp_k=new_core_temp_k,
            coolant_temp_k=new_coolant_temp_k,
            radiator_temp_k=new_rad_temp_k,
            heat_load_mw=heat_load_mw,
            heat_rejected_mw=P_rad_mw,
            thermal_margin=thermal_margin,
            radiator_area_m2=cfg.radiator_area_m2,
        )

    def radiator_mass_kg(self) -> float:
        """방열판 질량 [kg] = specific_mass [kg/m²] × area [m²]."""
        return self.config.specific_mass_kg_m2 * self.config.radiator_area_m2
