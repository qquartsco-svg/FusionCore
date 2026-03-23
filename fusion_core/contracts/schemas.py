"""
fusion_core/contracts/schemas.py
핵융합 코어 스택 데이터 계약 — 모든 상태 객체와 열거형 정의.

동역학 시스템 철학: 모든 상태값은 궤적 위의 관측값이며 추정값이다.
frozen dataclass를 통해 불변성을 보장한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Tuple


# ---------------------------------------------------------------------------
# 물리 상수 Config (NOT frozen — 주입 가능)
# ---------------------------------------------------------------------------

@dataclass
class FusionPhysicsConfig:
    """핵융합 물리 상수 컨테이너. 하드코딩 대신 이 객체를 주입한다."""

    k_b: float = 1.380649e-23         # J/K  볼츠만 상수
    e_charge: float = 1.602176634e-19  # C    기본 전하
    sigma_sb: float = 5.670374419e-8   # W/(m²·K⁴)  스테판-볼츠만 상수
    m_proton: float = 1.67262192e-27   # kg   양성자 질량
    ev_to_j: float = 1.602176634e-19   # eV → J
    kev_to_j: float = 1.602176634e-16  # keV → J
    mev_to_j: float = 1.602176634e-13  # MeV → J
    g0: float = 9.80665                # m/s²  표준 중력 가속도


# ---------------------------------------------------------------------------
# 열거형
# ---------------------------------------------------------------------------

class ReactionType(Enum):
    """지원하는 핵융합 반응 유형."""

    DT    = "D-T"    # 중수소-삼중수소 (현실적, 중성자 많음)
    DHE3  = "D-He3"  # 중수소-헬륨3  (저중성자, 고온 필요)
    DD    = "D-D"    # 중수소-중수소 (자원 풍부, 출력 낮음)
    PB11  = "p-B11"  # 수소-붕소11  (거의 무중성자, 극고온 필요)


class PlasmaPhase(Enum):
    """플라즈마 생애주기 상태.

    HIGH_Q_BURN: Q > sustained_q_threshold 조건에서 자가 유지 고Q 연소 추정 상태.
    실제 ignition(Q→∞) 달성이 아닌 고Q 수렴 근사 상태임에 유의.
    """

    COLD              = "COLD"
    PREHEATING        = "PREHEATING"
    IGNITION_ATTEMPT  = "IGNITION_ATTEMPT"
    BURNING           = "BURNING"
    HIGH_Q_BURN       = "HIGH_Q_BURN"   # 고Q 수렴 연소 (이상적 자가유지 근사)
    QUENCH            = "QUENCH"
    SHUTDOWN          = "SHUTDOWN"


class PropulsionMode(Enum):
    """추진 시스템 운용 모드."""

    OFF           = "OFF"
    ELECTRIC_ONLY = "ELECTRIC_ONLY"
    DIRECT_THRUST = "DIRECT_THRUST"
    HYBRID        = "HYBRID"


class AbortMode(Enum):
    """비상 중단 모드."""

    NONE                 = "NONE"
    CONTROLLED_SHUTDOWN  = "CONTROLLED_SHUTDOWN"
    EMERGENCY_QUENCH     = "EMERGENCY_QUENCH"
    MAGNETIC_DUMP        = "MAGNETIC_DUMP"


# ---------------------------------------------------------------------------
# 상태 데이터클래스 (frozen=True — 불변)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FuelState:
    """연료 저장 상태 스냅샷. 모든 질량 단위: kg."""

    deuterium_kg: float       # 중수소 잔량  [kg]
    tritium_kg: float         # 삼중수소 잔량 [kg]  (D-T 반응용)
    helium3_kg: float         # 헬륨-3 잔량  [kg]  (D-He3 반응용)
    total_fuel_kg: float      # 초기 총 연료량 (불변 참조) [kg]
    burnup_fraction: float    # 소모율 [0, 1]
    reaction_type: ReactionType

    def remaining_fraction(self) -> float:
        """현재 잔여 연료 분율 = (D + T + He3) / total_fuel_kg."""
        if self.total_fuel_kg <= 0.0:
            return 0.0
        return (self.deuterium_kg + self.tritium_kg + self.helium3_kg) / self.total_fuel_kg


@dataclass(frozen=True)
class PlasmaState:
    """플라즈마 물리 상태 스냅샷."""

    temperature_kev: float       # 플라즈마 온도       [keV]
    density_m3: float            # 입자 수밀도         [m⁻³]
    confinement_time_s: float    # 에너지 가둠 시간    [s]
    beta: float                  # 플라즈마 압력 / 자기 압력  [0, 1]
    q_factor: float              # 핵융합 이득  Q = P_fusion / P_heat
    triple_product: float        # n·τ·T               [keV·s/m³]
    heating_power_mw: float      # 외부 가열 전력      [MW]
    phase: PlasmaPhase


@dataclass(frozen=True)
class ReactionState:
    """핵융합 반응 출력 상태 스냅샷."""

    power_total_mw: float        # 총 핵융합 출력      [MW]
    power_charged_mw: float      # 하전입자 출력 (발전·직접추력 가능)  [MW]
    power_neutron_mw: float      # 중성자 출력 (차폐·열 부담)         [MW]
    reactivity_m3s: float        # <σv> 반응률         [m³/s]
    mass_flow_kgs: float         # 연료 소모율         [kg/s]
    charged_fraction: float      # 하전입자 에너지 분율
    reaction_type: ReactionType
    t_s: float                   # 시뮬레이션 시각     [s]


@dataclass(frozen=True)
class ThermalState:
    """열 관리 시스템 상태 스냅샷."""

    core_temp_k: float           # 반응로 코어 온도    [K]
    coolant_temp_k: float        # 냉각재 온도         [K]
    radiator_temp_k: float       # 방열판 온도         [K]
    heat_load_mw: float          # 총 열 부하          [MW]
    heat_rejected_mw: float      # 방열판 방출 열      [MW]
    thermal_margin: float        # (T_max - T_core) / T_max  [0, 1]
    radiator_area_m2: float      # 방열판 면적         [m²]


@dataclass(frozen=True)
class ShieldingState:
    """방사선 차폐 상태 스냅샷."""

    neutron_flux_m2s: float      # 중성자 플럭스       [m⁻²s⁻¹]
    dose_rate_sv_hr: float       # 선량률              [Sv/hr]
    shield_mass_kg: float        # 필요 차폐 질량      [kg]
    shield_thickness_m: float    # 필요 차폐 두께      [m]
    margin_fraction: float       # 1 - dose / dose_limit  [0, 1]


@dataclass(frozen=True)
class PowerBusState:
    """전력 버스 배분 상태 스냅샷."""

    total_available_mw: float    # 이용 가능 총 전력   [MW]
    electric_mw: float           # 전기계통 배분       [MW]
    thrust_mw: float             # 추진 배분           [MW]
    thermal_mgmt_mw: float       # 열관리 배분         [MW]
    parasitic_mw: float          # 기생 손실           [MW]
    allocation_efficiency: float  # 배분 효율          [0, 1]
    mode: PropulsionMode


@dataclass(frozen=True)
class FusionPropulsionState:
    """핵융합 추진 시스템 상태 스냅샷."""

    thrust_n: float                      # 추력                [N]
    isp_s: float                         # 비추력               [s]
    exhaust_vel_ms: float                # 배기 속도            [m/s]
    mass_flow_kgs: float                 # 추진제 유량          [kg/s]
    power_to_thrust_efficiency: float    # 전력→추력 효율
    mode: PropulsionMode


@dataclass(frozen=True)
class FusionCoreState:
    """핵융합 코어 전체 상태 스냅샷 — 모든 서브시스템 상태 통합."""

    t_s: float                           # 시뮬레이션 시각      [s]
    plasma: PlasmaState
    reaction: ReactionState
    thermal: ThermalState
    shielding: ShieldingState
    power_bus: PowerBusState
    propulsion: FusionPropulsionState
    fuel: FuelState

    def summary_dict(self) -> dict:
        """핵심 지표 요약 딕셔너리 반환."""
        return {
            "t_s": self.t_s,
            "plasma_temp_kev": self.plasma.temperature_kev,
            "plasma_phase": self.plasma.phase.value,
            "q_factor": self.plasma.q_factor,
            "power_total_mw": self.reaction.power_total_mw,
            "power_charged_mw": self.reaction.power_charged_mw,
            "power_neutron_mw": self.reaction.power_neutron_mw,
            "thermal_margin": self.thermal.thermal_margin,
            "dose_rate_sv_hr": self.shielding.dose_rate_sv_hr,
            "thrust_n": self.propulsion.thrust_n,
            "isp_s": self.propulsion.isp_s,
            "fuel_remaining": self.fuel.remaining_fraction(),
            "propulsion_mode": self.propulsion.mode.value,
        }


@dataclass(frozen=True)
class FusionHealth:
    """핵융합 코어 건전성 지표 스냅샷."""

    omega_fusion: float      # 종합 건전성  [0, 1]
    omega_plasma: float      # 플라즈마 건전성
    omega_thermal: float     # 열 건전성
    omega_shielding: float   # 차폐 건전성
    omega_fuel: float        # 연료 건전성
    omega_power: float       # 전력 건전성
    verdict: str             # "HEALTHY" / "STABLE" / "FRAGILE" / "CRITICAL"
    alerts: tuple            # 경보 목록 (str 요소)
    abort_required: bool


@dataclass(frozen=True)
class TelemetryFrame:
    """단일 시각의 원격측정 프레임 — 상태 + 건전성 + 위상 + 중단 모드."""

    t_s: float
    state: FusionCoreState
    health: FusionHealth
    phase: PlasmaPhase
    abort_mode: AbortMode

    def summary_dict(self) -> dict:
        """요약 딕셔너리 반환 (로그·감사 용도)."""
        return {
            "t_s": self.t_s,
            "phase": self.phase.value,
            "abort_mode": self.abort_mode.value,
            "omega_fusion": self.health.omega_fusion,
            "verdict": self.health.verdict,
            "abort_required": self.health.abort_required,
            **self.state.summary_dict(),
        }
