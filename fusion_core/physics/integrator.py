"""
fusion_core/physics/integrator.py
RK4(4차 룽게-쿠타) 수치 적분기 모듈.

연료 질량, 방열판 온도, 플라즈마 온도를 RK4로 적분한다.
stdlib만 사용, 외부 의존성 없음.
"""

from __future__ import annotations

from fusion_core.contracts.schemas import FuelState, ThermalState
from fusion_core.physics.thermal import ThermalConfig


class FusionIntegrator:
    """핵융합 코어 상태 변수 RK4 적분기."""

    @staticmethod
    def _rk4(f, y0: float, dt: float, *args) -> float:
        """
        스칼라 RK4 적분.

        f(y, *args) → dy/dt
        """
        k1 = f(y0, *args)
        k2 = f(y0 + 0.5 * dt * k1, *args)
        k3 = f(y0 + 0.5 * dt * k2, *args)
        k4 = f(y0 + dt * k3, *args)
        return y0 + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)

    def step_fuel(
        self,
        fuel: FuelState,
        mass_flow_kgs: float,
        dt_s: float,
    ) -> FuelState:
        """
        RK4로 연료 질량 갱신.

        dm/dt = -mass_flow  (D와 T/He3 비율에 따라 분배)
        """
        # D-T 기준: D와 T 동등 소모
        # 전체 연료 총질량 감소를 반응 파트너 비율로 분배
        total = fuel.deuterium_kg + fuel.tritium_kg + fuel.helium3_kg
        if total <= 0.0 or mass_flow_kgs <= 0.0:
            return fuel

        def dm_dt(m: float, flow: float) -> float:
            return -flow

        # 연료 비율로 각 성분 소모
        frac_d  = fuel.deuterium_kg / total if total > 0 else 0.33
        frac_t  = fuel.tritium_kg   / total if total > 0 else 0.33
        frac_he = fuel.helium3_kg   / total if total > 0 else 0.34

        new_d   = self._rk4(dm_dt, fuel.deuterium_kg, dt_s, mass_flow_kgs * frac_d)
        new_t   = self._rk4(dm_dt, fuel.tritium_kg,   dt_s, mass_flow_kgs * frac_t)
        new_he  = self._rk4(dm_dt, fuel.helium3_kg,   dt_s, mass_flow_kgs * frac_he)

        new_d  = max(0.0, new_d)
        new_t  = max(0.0, new_t)
        new_he = max(0.0, new_he)

        remaining = new_d + new_t + new_he
        burnup = 1.0 - (remaining / fuel.total_fuel_kg) if fuel.total_fuel_kg > 0 else 1.0

        return FuelState(
            deuterium_kg=new_d,
            tritium_kg=new_t,
            helium3_kg=new_he,
            total_fuel_kg=fuel.total_fuel_kg,
            burnup_fraction=max(0.0, min(1.0, burnup)),
            reaction_type=fuel.reaction_type,
        )

    def step_thermal(
        self,
        state: ThermalState,
        heat_load_mw: float,
        heat_rejected_mw: float,
        dt_s: float,
        config: ThermalConfig,
    ) -> ThermalState:
        """
        RK4로 방열판 온도 갱신.

        dT/dt = (Q_in - Q_out) * 1e6 / C_thermal
        """
        C = config.coolant_heat_capacity_j_per_k

        def dT_dt(T: float, q_in: float, q_out: float) -> float:
            return (q_in - q_out) * 1.0e6 / C

        new_rad_temp = self._rk4(dT_dt, state.radiator_temp_k, dt_s,
                                  heat_load_mw, heat_rejected_mw)
        new_rad_temp = max(3.0, new_rad_temp)

        # 코어/냉각재 온도 추산 (열저항 모델)
        thermal_resistance_k_per_w = 1.0e-7
        delta_t = heat_load_mw * 1.0e6 * thermal_resistance_k_per_w
        new_core = new_rad_temp + delta_t
        new_coolant = (new_core + new_rad_temp) / 2.0

        margin = (config.max_core_temp_k - new_core) / config.max_core_temp_k
        margin = max(-1.0, min(1.0, margin))

        return ThermalState(
            core_temp_k=new_core,
            coolant_temp_k=new_coolant,
            radiator_temp_k=new_rad_temp,
            heat_load_mw=heat_load_mw,
            heat_rejected_mw=heat_rejected_mw,
            thermal_margin=margin,
            radiator_area_m2=state.radiator_area_m2,
        )

    def step_plasma_temp(
        self,
        T_kev: float,
        heating_mw: float,
        fusion_alpha_mw: float,
        losses_mw: float,
        heat_capacity_j_per_kev: float,
        dt_s: float,
    ) -> float:
        """
        RK4로 플라즈마 온도 갱신 [keV].

        dT/dt = (P_heat + P_alpha - P_loss) / C  [keV/s]
        """
        def dT_dt(T: float, h: float, alpha: float, loss: float, C: float) -> float:
            if C <= 0.0:
                return 0.0
            return (h + alpha - loss) / C

        new_T = self._rk4(
            dT_dt, T_kev, dt_s,
            heating_mw, fusion_alpha_mw, losses_mw, heat_capacity_j_per_kev
        )
        return max(0.001, new_T)  # 온도는 양수
