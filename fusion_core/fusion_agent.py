"""
fusion_core/fusion_agent.py
핵융합 코어 에이전트 — 전체 시뮬레이션 파이프라인 통합 오케스트레이터.

tick() 10단계 파이프라인:
  1.  PlasmaFSM.update(ctx)              → phase
  2.  FusionReactor.tick(...)            → (reaction, fuel)
  3.  FusionIntegrator.step_plasma_temp  → T_kev 갱신
  4.  ConfinementModel.assess(plasma)    → plasma 갱신
  5.  ThermalSystem.tick(heat_load)      → thermal
  6.  ShieldingModel.tick(reaction)      → shielding
  7.  PowerBusController.allocate(...)   → power_bus
  8.  FusionPropulsionEngine.tick(...)   → propulsion
  9.  OmegaMonitor.observe(state)        → health
  10. AbortSystem.evaluate(...)          → abort_mode
      + FusionChain.record(frame)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from fusion_core.audit.fusion_chain import FusionChain
from fusion_core.contracts.schemas import (
    AbortMode,
    FuelState,
    FusionCoreState,
    FusionHealth,
    FusionPhysicsConfig,
    FusionPropulsionState,
    PlasmaPhase,
    PlasmaState,
    PowerBusState,
    PropulsionMode,
    ReactionState,
    ReactionType,
    ShieldingState,
    TelemetryFrame,
    ThermalState,
)
from fusion_core.physics.integrator import FusionIntegrator
from fusion_core.physics.propulsion import FusionPropulsionConfig, FusionPropulsionEngine
from fusion_core.physics.reaction import FusionReactor, ReactionConfig
from fusion_core.physics.shielding import ShieldingConfig, ShieldingModel
from fusion_core.physics.thermal import ThermalConfig, ThermalSystem
from fusion_core.plasma.confinement import ConfinementConfig, ConfinementModel
from fusion_core.plasma.plasma_fsm import PlasmaFSM, PlasmaFSMConfig, PlasmaFSMContext
from fusion_core.power.power_bus import PowerBusConfig, PowerBusController
from fusion_core.safety.abort_system import AbortConfig, AbortSystem
from fusion_core.safety.omega_monitor import OmegaConfig, OmegaMonitor


@dataclass
class FusionAgentConfig:
    """FusionAgent 전체 설정 묶음."""

    reactor_id: str = "FC-001"
    dt_s: float = 1.0
    reaction_config: ReactionConfig = field(default_factory=ReactionConfig)
    thermal_config: ThermalConfig = field(default_factory=ThermalConfig)
    shielding_config: ShieldingConfig = field(default_factory=ShieldingConfig)
    propulsion_config: FusionPropulsionConfig = field(default_factory=FusionPropulsionConfig)
    confinement_config: ConfinementConfig = field(default_factory=ConfinementConfig)
    plasma_fsm_config: PlasmaFSMConfig = field(default_factory=PlasmaFSMConfig)
    power_bus_config: PowerBusConfig = field(default_factory=PowerBusConfig)
    omega_config: OmegaConfig = field(default_factory=OmegaConfig)
    abort_config: AbortConfig = field(default_factory=AbortConfig)
    physics: FusionPhysicsConfig = field(default_factory=FusionPhysicsConfig)
    chain_record_interval: int = 10


def _make_initial_plasma() -> PlasmaState:
    """초기 플라즈마 상태 (COLD)."""
    return PlasmaState(
        temperature_kev=0.1,
        density_m3=1.0e20,
        confinement_time_s=3.0,
        beta=0.001,
        q_factor=0.0,
        triple_product=0.0,
        heating_power_mw=0.0,
        phase=PlasmaPhase.COLD,
    )


def _make_initial_fuel(reaction_type: ReactionType = ReactionType.DT) -> FuelState:
    """초기 연료 상태."""
    total = 1000.0  # kg
    if reaction_type == ReactionType.DT:
        return FuelState(
            deuterium_kg=500.0,
            tritium_kg=500.0,
            helium3_kg=0.0,
            total_fuel_kg=total,
            burnup_fraction=0.0,
            reaction_type=reaction_type,
        )
    elif reaction_type == ReactionType.DHE3:
        return FuelState(
            deuterium_kg=500.0,
            tritium_kg=0.0,
            helium3_kg=500.0,
            total_fuel_kg=total,
            burnup_fraction=0.0,
            reaction_type=reaction_type,
        )
    elif reaction_type == ReactionType.DD:
        return FuelState(
            deuterium_kg=1000.0,
            tritium_kg=0.0,
            helium3_kg=0.0,
            total_fuel_kg=total,
            burnup_fraction=0.0,
            reaction_type=reaction_type,
        )
    else:
        return FuelState(
            deuterium_kg=500.0,
            tritium_kg=0.0,
            helium3_kg=0.0,
            total_fuel_kg=total,
            burnup_fraction=0.0,
            reaction_type=reaction_type,
        )


def _make_initial_thermal(config: ThermalConfig) -> ThermalState:
    return ThermalState(
        core_temp_k=300.0,
        coolant_temp_k=300.0,
        radiator_temp_k=config.initial_radiator_temp_k,
        heat_load_mw=0.0,
        heat_rejected_mw=0.0,
        thermal_margin=1.0,
        radiator_area_m2=config.radiator_area_m2,
    )


def _make_initial_shielding() -> ShieldingState:
    return ShieldingState(
        neutron_flux_m2s=0.0,
        dose_rate_sv_hr=0.0,
        shield_mass_kg=0.0,
        shield_thickness_m=0.0,
        margin_fraction=1.0,
    )


def _make_initial_power_bus(mode: PropulsionMode = PropulsionMode.OFF) -> PowerBusState:
    return PowerBusState(
        total_available_mw=0.0,
        electric_mw=0.0,
        thrust_mw=0.0,
        thermal_mgmt_mw=0.0,
        parasitic_mw=0.0,
        allocation_efficiency=0.0,
        mode=mode,
    )


def _make_initial_propulsion(mode: PropulsionMode = PropulsionMode.OFF) -> FusionPropulsionState:
    return FusionPropulsionState(
        thrust_n=0.0,
        isp_s=5000.0,
        exhaust_vel_ms=5000.0 * 9.80665,
        mass_flow_kgs=0.0,
        power_to_thrust_efficiency=0.0,
        mode=mode,
    )


def _make_initial_reaction(reaction_type: ReactionType = ReactionType.DT) -> ReactionState:
    return ReactionState(
        power_total_mw=0.0,
        power_charged_mw=0.0,
        power_neutron_mw=0.0,
        reactivity_m3s=0.0,
        mass_flow_kgs=0.0,
        charged_fraction=0.1989,
        reaction_type=reaction_type,
        t_s=0.0,
    )


class FusionAgent:
    """
    핵융합 코어 에이전트.

    전체 서브시스템을 통합하여 매 시각(tick)마다
    물리 시뮬레이션 파이프라인을 실행하고 TelemetryFrame을 생성한다.
    """

    def __init__(self, config: FusionAgentConfig | None = None) -> None:
        self.cfg = config or FusionAgentConfig()

        # 서브시스템 인스턴스화
        self._reactor     = FusionReactor(self.cfg.reaction_config)
        self._thermal_sys = ThermalSystem(self.cfg.thermal_config)
        self._shielding   = ShieldingModel(self.cfg.shielding_config)
        self._propulsion  = FusionPropulsionEngine(self.cfg.propulsion_config)
        self._confinement = ConfinementModel(self.cfg.confinement_config)
        self._fsm         = PlasmaFSM(self.cfg.plasma_fsm_config)
        self._power_bus   = PowerBusController()
        self._omega       = OmegaMonitor()
        self._abort_sys   = AbortSystem(self.cfg.abort_config)
        self._integrator  = FusionIntegrator()
        self._chain       = FusionChain(self.cfg.reactor_id, self.cfg.chain_record_interval)

        # 가변 상태
        self._t_s: float = 0.0
        self._throttle: float = 0.5
        self._mode: PropulsionMode = PropulsionMode.OFF
        self._go_command: bool = False
        self._abort_trigger: bool = False

        # 초기 상태 구성
        rt = self.cfg.reaction_config.reaction_type
        self._plasma   = _make_initial_plasma()
        self._fuel     = _make_initial_fuel(rt)
        self._thermal  = _make_initial_thermal(self.cfg.thermal_config)
        self._shielding_state = _make_initial_shielding()
        self._power_bus_state = _make_initial_power_bus(self._mode)
        self._propulsion_state = _make_initial_propulsion(self._mode)
        self._reaction = _make_initial_reaction(rt)

        # 플라즈마 열용량 [MW/keV] — 단순 추정
        # C = 3/2 * n * V * k_B [J/keV] * kev_to_j 역수
        # 여기서는 실용적인 스케일 파라미터 사용
        self._plasma_heat_capacity_mw_per_kev: float = 50.0

    # ------------------------------------------------------------------
    # 제어 인터페이스
    # ------------------------------------------------------------------

    def ignite(self) -> None:
        """점화 명령 (go_command = True)."""
        self._go_command = True

    def shutdown(self) -> None:
        """비상 중단 (abort_trigger = True)."""
        self._abort_trigger = True

    def set_mode(self, mode: PropulsionMode) -> None:
        """추진 모드 설정."""
        self._mode = mode

    def set_throttle(self, throttle: float) -> None:
        """스로틀 설정 [0, 1]."""
        self._throttle = max(0.0, min(1.0, throttle))

    def get_health(self) -> FusionHealth:
        """마지막 계산된 건전성 반환."""
        return self._last_health if hasattr(self, "_last_health") else self._omega.observe(
            self._make_core_state(), self.cfg.omega_config
        )

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _make_core_state(self) -> FusionCoreState:
        return FusionCoreState(
            t_s=self._t_s,
            plasma=self._plasma,
            reaction=self._reaction,
            thermal=self._thermal,
            shielding=self._shielding_state,
            power_bus=self._power_bus_state,
            propulsion=self._propulsion_state,
            fuel=self._fuel,
        )

    # ------------------------------------------------------------------
    # 메인 tick 파이프라인
    # ------------------------------------------------------------------

    def tick(self) -> TelemetryFrame:
        """
        10단계 물리 파이프라인 1틱 실행.

        불변 상태 객체들을 순차적으로 갱신하고
        TelemetryFrame을 반환한다.
        """
        t = self._t_s
        dt = self.cfg.dt_s
        phys = self.cfg.physics

        # ----------------------------------------------------------
        # 1. PlasmaFSM.update → phase
        # ----------------------------------------------------------
        lawson_ok = self._confinement.lawson_satisfied(
            self._plasma, self.cfg.reaction_config.reaction_type
        )
        ctx = PlasmaFSMContext(
            t_s=t,
            plasma_temp_kev=self._plasma.temperature_kev,
            q_factor=self._plasma.q_factor,
            beta=self._plasma.beta,
            lawson_satisfied=lawson_ok,
            abort_trigger=self._abort_trigger,
            go_command=self._go_command,
            heating_available=True,
        )
        phase = self._fsm.update(ctx)

        # ----------------------------------------------------------
        # 2. FusionReactor.tick → (reaction, fuel)
        # ----------------------------------------------------------
        # 가열 전력: 위상에 따라 스케일
        if phase in (PlasmaPhase.PREHEATING, PlasmaPhase.IGNITION_ATTEMPT):
            heating_mw = 50.0 * self._throttle   # 외부 가열 전력 [MW]
        elif phase in (PlasmaPhase.BURNING, PlasmaPhase.HIGH_Q_BURN):
            heating_mw = 10.0 * self._throttle   # 유지 가열
        else:
            heating_mw = 0.0

        reaction, new_fuel = self._reactor.tick(
            self._plasma, self._fuel, self._throttle, dt, phys
        )
        # t_s 주입 (reaction.t_s는 0으로 생성됨)
        reaction = ReactionState(
            power_total_mw=reaction.power_total_mw,
            power_charged_mw=reaction.power_charged_mw,
            power_neutron_mw=reaction.power_neutron_mw,
            reactivity_m3s=reaction.reactivity_m3s,
            mass_flow_kgs=reaction.mass_flow_kgs,
            charged_fraction=reaction.charged_fraction,
            reaction_type=reaction.reaction_type,
            t_s=t,
        )

        # ----------------------------------------------------------
        # 3. FusionIntegrator.step_plasma_temp → T_kev 갱신
        # ----------------------------------------------------------
        alpha_mw = reaction.power_charged_mw  # 알파 자가 가열 프록시
        losses_mw = self._plasma.temperature_kev * 5.0  # 단순 손실 모델 (비례)
        new_T_kev = self._integrator.step_plasma_temp(
            T_kev=self._plasma.temperature_kev,
            heating_mw=heating_mw,
            fusion_alpha_mw=alpha_mw * 0.2,   # 알파 입자 에너지 일부 플라즈마 가열
            losses_mw=losses_mw,
            heat_capacity_j_per_kev=self._plasma_heat_capacity_mw_per_kev,
            dt_s=dt,
        )
        # QUENCH/SHUTDOWN: 급냉
        if phase in (PlasmaPhase.QUENCH, PlasmaPhase.SHUTDOWN):
            new_T_kev = max(0.1, new_T_kev * 0.5)

        # ----------------------------------------------------------
        # 4. ConfinementModel.assess → plasma 갱신
        # ----------------------------------------------------------
        interim_plasma = PlasmaState(
            temperature_kev=new_T_kev,
            density_m3=self._plasma.density_m3,
            confinement_time_s=self._confinement.config.energy_confinement_time_s,
            beta=self._plasma.beta,
            q_factor=self._plasma.q_factor,
            triple_product=self._plasma.triple_product,
            heating_power_mw=heating_mw,
            phase=phase,
        )
        new_plasma = self._confinement.assess(
            interim_plasma,
            self.cfg.reaction_config.reaction_type,
            heating_mw,
            phys,
        )
        # phase 갱신 (confinement는 phase를 변경하지 않음 — FSM 결과 유지)
        new_plasma = PlasmaState(
            temperature_kev=new_plasma.temperature_kev,
            density_m3=new_plasma.density_m3,
            confinement_time_s=new_plasma.confinement_time_s,
            beta=new_plasma.beta,
            q_factor=new_plasma.q_factor,
            triple_product=new_plasma.triple_product,
            heating_power_mw=new_plasma.heating_power_mw,
            phase=phase,
        )

        # ----------------------------------------------------------
        # 5. ThermalSystem.tick → thermal
        # ----------------------------------------------------------
        heat_load_mw = reaction.power_neutron_mw + reaction.power_total_mw * 0.05
        new_thermal = self._thermal_sys.tick(heat_load_mw, dt, self._thermal, phys)

        # ----------------------------------------------------------
        # 6. ShieldingModel.tick → shielding
        # ----------------------------------------------------------
        new_shielding = self._shielding.tick(reaction, phys)

        # ----------------------------------------------------------
        # 7. PowerBusController.allocate → power_bus
        # ----------------------------------------------------------
        new_power_bus = self._power_bus.allocate(
            reaction, self._mode, self.cfg.power_bus_config
        )

        # ----------------------------------------------------------
        # 8. FusionPropulsionEngine.tick → propulsion
        # ----------------------------------------------------------
        new_propulsion = self._propulsion.tick(new_power_bus, phys)

        # ----------------------------------------------------------
        # 9. 전체 상태 조합
        # ----------------------------------------------------------
        core_state = FusionCoreState(
            t_s=t,
            plasma=new_plasma,
            reaction=reaction,
            thermal=new_thermal,
            shielding=new_shielding,
            power_bus=new_power_bus,
            propulsion=new_propulsion,
            fuel=new_fuel,
        )

        # ----------------------------------------------------------
        # 10. OmegaMonitor.observe → health
        #     AbortSystem.evaluate → abort_mode
        # ----------------------------------------------------------
        health = self._omega.observe(core_state, self.cfg.omega_config)
        abort_mode = self._abort_sys.evaluate(
            health, core_state, phase, self._abort_trigger
        )

        # abort_mode에 따른 phase 보정
        final_phase = phase
        if abort_mode != AbortMode.NONE and phase not in (PlasmaPhase.SHUTDOWN, PlasmaPhase.QUENCH):
            if abort_mode == AbortMode.EMERGENCY_QUENCH:
                final_phase = PlasmaPhase.SHUTDOWN
            elif abort_mode in (AbortMode.CONTROLLED_SHUTDOWN, AbortMode.MAGNETIC_DUMP):
                final_phase = PlasmaPhase.QUENCH

        if final_phase != new_plasma.phase:
            new_plasma = PlasmaState(
                temperature_kev=new_plasma.temperature_kev,
                density_m3=new_plasma.density_m3,
                confinement_time_s=new_plasma.confinement_time_s,
                beta=new_plasma.beta,
                q_factor=new_plasma.q_factor,
                triple_product=new_plasma.triple_product,
                heating_power_mw=new_plasma.heating_power_mw,
                phase=final_phase,
            )
            core_state = FusionCoreState(
                t_s=t,
                plasma=new_plasma,
                reaction=reaction,
                thermal=new_thermal,
                shielding=new_shielding,
                power_bus=new_power_bus,
                propulsion=new_propulsion,
                fuel=new_fuel,
            )

        frame = TelemetryFrame(
            t_s=t,
            state=core_state,
            health=health,
            phase=final_phase,
            abort_mode=abort_mode,
        )

        # 체인 기록
        self._chain.record(frame)

        # 이벤트 기록 (상태 전이 감지)
        prev_phase = self._plasma.phase
        if final_phase != prev_phase:
            event_type = {
                PlasmaPhase.BURNING:  "IGNITION",
                PlasmaPhase.QUENCH:   "QUENCH",
                PlasmaPhase.SHUTDOWN: "ABORT",
            }.get(final_phase, "STAGE_EVENT")
            self._chain.record_event(t, event_type, {
                "from_phase": prev_phase.value,
                "to_phase": final_phase.value,
            })

        # 상태 갱신
        self._plasma          = new_plasma
        self._fuel            = new_fuel
        self._thermal         = new_thermal
        self._shielding_state = new_shielding
        self._power_bus_state = new_power_bus
        self._propulsion_state = new_propulsion
        self._reaction        = reaction
        self._last_health     = health

        self._t_s += dt
        return frame

    # ------------------------------------------------------------------
    # 시뮬레이션 헬퍼
    # ------------------------------------------------------------------

    def simulate(self, duration_s: float) -> list[TelemetryFrame]:
        """
        duration_s 동안 시뮬레이션 실행.

        매 dt_s마다 tick()을 호출하고 TelemetryFrame 목록을 반환한다.
        """
        n_steps = max(1, int(duration_s / self.cfg.dt_s))
        frames: list[TelemetryFrame] = []
        for _ in range(n_steps):
            frames.append(self.tick())
        return frames
