"""
fusion_core/physics/reaction.py
핵융합 반응률 및 출력 계산 모듈.

반응별 <σv> 데이터는 NRL Plasma Formulary 기반 조각선형 보간.
모든 상태 변환은 FusionPhysicsConfig를 통해 상수를 주입받는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from fusion_core.contracts.schemas import (
    FuelState,
    FusionPhysicsConfig,
    PlasmaState,
    ReactionState,
    ReactionType,
)


# ---------------------------------------------------------------------------
# 반응별 에너지 분율 상수 (반응 유형별 고정값 — config 주입 대상)
# ---------------------------------------------------------------------------
# D-T:    charged=3.5 MeV, neutron=14.1 MeV, total=17.6 MeV  → frac=0.1989
# D-He3:  charged≈18.3 MeV, neutron≈0 (소량 D-D 부반응)       → frac≈0.94
# D-D:    복수 경로 평균                                         → frac≈0.67
# p-B11:  charged≈8.7 MeV (세 알파), total≈8.7 MeV            → frac≈0.99

_CHARGED_FRACTION = {
    ReactionType.DT:   0.1989,
    ReactionType.DHE3: 0.94,
    ReactionType.DD:   0.67,
    ReactionType.PB11: 0.99,
}

# 반응별 총 Q 값 [MeV]
_Q_MEV = {
    ReactionType.DT:   17.6,
    ReactionType.DHE3: 18.3,
    ReactionType.DD:   3.65,   # 두 채널 평균 (D-T+p 및 He3+n)
    ReactionType.PB11: 8.7,
}

# 연료 분자량 [kg/mol → 입자당 kg] 근사
# D-T 반응: D(2u) + T(3u) → 각 쌍 소모 질량 ≈ 5u
_AMU = 1.66053906660e-27  # kg


@dataclass
class ReactionConfig:
    """핵융합 반응기 설정."""

    reaction_type: ReactionType = ReactionType.DT
    chamber_volume_m3: float = 100.0      # 반응 챔버 체적    [m³]
    fuel_mix_ratio: float = 0.5           # D/(D+T) 비율 (D-T에서 0.5 최적)
    min_ignition_temp_kev: float = 4.0    # 최소 점화 온도    [keV]


def _lerp(x: float, xs: list[float], ys: list[float]) -> float:
    """조각선형 보간. 범위 외는 끝단 값으로 클램프."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            t = (x - xs[i]) / (xs[i + 1] - xs[i])
            return ys[i] + t * (ys[i + 1] - ys[i])
    return ys[-1]


class FusionReactor:
    """핵융합 반응률과 출력을 계산하는 물리 엔진."""

    def __init__(self, config: ReactionConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # 반응률 <σv> [m³/s]
    # ------------------------------------------------------------------

    def _reactivity_dt(self, T_kev: float) -> float:
        """D-T 반응률 <σv> [m³/s] — NRL 데이터 기반 조각선형 보간."""
        # 단위: T [keV], <σv> [m³/s]
        T_data   = [1.0,    2.0,    5.0,    10.0,   20.0,   50.0,   100.0,  200.0]
        sv_data  = [6.60e-27, 4.56e-25, 1.27e-23, 1.12e-22,
                    4.33e-22, 8.29e-22, 8.12e-22, 6.29e-22]
        return max(0.0, _lerp(T_kev, T_data, sv_data))

    def _reactivity_dhe3(self, T_kev: float) -> float:
        """D-He3 반응률 <σv> [m³/s] — 고온 필요."""
        T_data   = [10.0,    20.0,    50.0,    100.0,   200.0,   500.0]
        sv_data  = [2.78e-26, 8.93e-25, 1.14e-22, 2.54e-22, 2.41e-22, 1.29e-22]
        return max(0.0, _lerp(T_kev, T_data, sv_data))

    def _reactivity_dd(self, T_kev: float) -> float:
        """D-D 반응률 <σv> [m³/s] (두 채널 합산)."""
        T_data   = [1.0,    2.0,    5.0,    10.0,   20.0,   50.0,   100.0]
        sv_data  = [2.81e-28, 4.44e-27, 1.84e-25, 1.40e-24, 7.68e-24,
                    3.60e-23, 8.92e-23]
        return max(0.0, _lerp(T_kev, T_data, sv_data))

    def _reactivity_pb11(self, T_kev: float) -> float:
        """p-B11 반응률 <σv> [m³/s] — 극고온 필요 (단순 근사)."""
        # 대략적인 데이터 포인트 (keV 기준 초고온 영역)
        T_data   = [100.0,   200.0,   300.0,   500.0,   1000.0]
        sv_data  = [1.0e-27, 1.5e-26, 8.0e-26, 2.0e-25, 4.0e-25]
        return max(0.0, _lerp(T_kev, T_data, sv_data))

    def reactivity(self, T_kev: float) -> float:
        """반응 유형에 따른 <σv> [m³/s] 반환."""
        rt = self.config.reaction_type
        if rt == ReactionType.DT:
            return self._reactivity_dt(T_kev)
        elif rt == ReactionType.DHE3:
            return self._reactivity_dhe3(T_kev)
        elif rt == ReactionType.DD:
            return self._reactivity_dd(T_kev)
        elif rt == ReactionType.PB11:
            return self._reactivity_pb11(T_kev)
        return 0.0

    def reaction_power_density(
        self,
        n_d: float,   # 중수소 수밀도  [m⁻³]
        n_t: float,   # 반응 파트너 수밀도  [m⁻³]  (T 또는 He3 등)
        T_kev: float,
    ) -> float:
        """단위 체적당 출력 [W/m³] = n_D · n_T · <σv> · E_fusion_J."""
        sv = self.reactivity(T_kev)
        Q_j = _Q_MEV[self.config.reaction_type] * 1.602176634e-13  # MeV → J
        return n_d * n_t * sv * Q_j  # [W/m³]

    def tick(
        self,
        plasma: PlasmaState,
        fuel: FuelState,
        throttle: float,
        dt_s: float,
        physics: FusionPhysicsConfig,
    ) -> tuple[ReactionState, FuelState]:
        """
        1틱 핵융합 반응 계산.

        throttle [0, 1]: 가열 전력 비율 → 유효 플라즈마 밀도 제어 프록시.
        최소 점화 온도 미달 시 power=0.
        """
        T_kev = plasma.temperature_kev
        rt = self.config.reaction_type

        # 점화 조건 확인
        if T_kev < self.config.min_ignition_temp_kev:
            sv = 0.0
            power_density = 0.0
        else:
            # 유효 밀도: throttle로 스케일 (플라즈마 밀도 제어 프록시)
            n_total = plasma.density_m3 * max(0.0, min(1.0, throttle))
            r = self.config.fuel_mix_ratio
            n_d = n_total * r
            n_t = n_total * (1.0 - r)
            sv = self.reactivity(T_kev)
            power_density = self.reaction_power_density(n_d, n_t, T_kev)

        # 총 출력 [MW]
        power_total_w = power_density * self.config.chamber_volume_m3
        power_total_mw = power_total_w * 1e-6

        charged_frac = _CHARGED_FRACTION[rt]
        power_charged_mw = power_total_mw * charged_frac
        power_neutron_mw = power_total_mw * (1.0 - charged_frac)

        # 연료 소모율 [kg/s]: E = m·c²·η 대신 핵반응 에너지 직접 계산
        Q_j = _Q_MEV[rt] * physics.mev_to_j
        # 반응 쌍 수/s = power_total_w / Q_j
        reactions_per_s = power_total_w / Q_j if Q_j > 0 else 0.0
        # 쌍 당 소모 질량: D-T ≈ 5 amu, D-He3 ≈ 5 amu, D-D ≈ 4 amu, p-B11 ≈ 12 amu
        pair_mass = {
            ReactionType.DT:   5.0 * _AMU,
            ReactionType.DHE3: 5.0 * _AMU,
            ReactionType.DD:   4.0 * _AMU,
            ReactionType.PB11: 12.0 * _AMU,
        }[rt]
        mass_flow_kgs = reactions_per_s * pair_mass

        # 연료 상태 갱신 (불변 → 새 객체)
        d_consumed = mass_flow_kgs * dt_s * self.config.fuel_mix_ratio
        t_or_he3_consumed = mass_flow_kgs * dt_s * (1.0 - self.config.fuel_mix_ratio)

        new_d = max(0.0, fuel.deuterium_kg - d_consumed)
        new_t = fuel.tritium_kg
        new_he3 = fuel.helium3_kg
        if rt in (ReactionType.DT, ReactionType.DD):
            new_t = max(0.0, fuel.tritium_kg - t_or_he3_consumed)
        elif rt == ReactionType.DHE3:
            new_he3 = max(0.0, fuel.helium3_kg - t_or_he3_consumed)

        total_remaining = new_d + new_t + new_he3
        burnup = 1.0 - (total_remaining / fuel.total_fuel_kg) if fuel.total_fuel_kg > 0 else 1.0

        new_fuel = FuelState(
            deuterium_kg=new_d,
            tritium_kg=new_t,
            helium3_kg=new_he3,
            total_fuel_kg=fuel.total_fuel_kg,
            burnup_fraction=max(0.0, min(1.0, burnup)),
            reaction_type=rt,
        )

        reaction_state = ReactionState(
            power_total_mw=max(0.0, power_total_mw),
            power_charged_mw=max(0.0, power_charged_mw),
            power_neutron_mw=max(0.0, power_neutron_mw),
            reactivity_m3s=sv,
            mass_flow_kgs=mass_flow_kgs,
            charged_fraction=charged_frac,
            reaction_type=rt,
            t_s=plasma.phase.value and 0.0 or 0.0,  # t_s는 agent에서 주입
        )

        return reaction_state, new_fuel
