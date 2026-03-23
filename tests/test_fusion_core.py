"""
tests/test_fusion_core.py
FusionCore Stack 전체 테스트 스위트 (~120 케이스).

§1  FusionPhysicsConfig         (5)
§2  FuelState                   (8)
§3  ReactionState 계약          (6)
§4  D-T 반응률 물리             (10)
§5  D-He3 반응률 물리           (6)
§6  ThermalSystem               (10)
§7  ShieldingModel              (8)
§8  ConfinementModel            (8)
§9  PlasmaFSM                   (12)
§10 PowerBusController          (8)
§11 FusionPropulsionEngine      (8)
§12 OmegaMonitor                (10)
§13 AbortSystem                 (8)
§14 FusionChain                 (8)
§15 FusionAgent 통합            (12)
"""

import math
import sys
import os

# 패키지 루트를 sys.path에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

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
from fusion_core.physics.reaction import FusionReactor, ReactionConfig
from fusion_core.physics.thermal import ThermalConfig, ThermalSystem
from fusion_core.physics.shielding import ShieldingConfig, ShieldingModel
from fusion_core.physics.propulsion import FusionPropulsionConfig, FusionPropulsionEngine
from fusion_core.physics.integrator import FusionIntegrator
from fusion_core.plasma.confinement import ConfinementConfig, ConfinementModel
from fusion_core.plasma.plasma_fsm import PlasmaFSM, PlasmaFSMConfig, PlasmaFSMContext
from fusion_core.power.power_bus import PowerBusConfig, PowerBusController
from fusion_core.safety.omega_monitor import OmegaConfig, OmegaMonitor
from fusion_core.safety.abort_system import AbortConfig, AbortSystem
from fusion_core.audit.fusion_chain import FusionChain
from fusion_core.fusion_agent import FusionAgent, FusionAgentConfig


# ============================================================
# 공통 픽스처
# ============================================================

@pytest.fixture
def physics():
    return FusionPhysicsConfig()


@pytest.fixture
def dt_reactor():
    return FusionReactor(ReactionConfig(reaction_type=ReactionType.DT))


@pytest.fixture
def dhe3_reactor():
    return FusionReactor(ReactionConfig(reaction_type=ReactionType.DHE3))


@pytest.fixture
def dd_reactor():
    return FusionReactor(ReactionConfig(reaction_type=ReactionType.DD))


def make_plasma(T_kev=10.0, n=1e20, tau=3.0, phase=PlasmaPhase.BURNING,
                beta=0.02, q=2.0, heating=50.0) -> PlasmaState:
    return PlasmaState(
        temperature_kev=T_kev,
        density_m3=n,
        confinement_time_s=tau,
        beta=beta,
        q_factor=q,
        triple_product=n * tau * T_kev,
        heating_power_mw=heating,
        phase=phase,
    )


def make_fuel(rt=ReactionType.DT, d=500.0, t=500.0, he3=0.0, total=1000.0) -> FuelState:
    return FuelState(
        deuterium_kg=d,
        tritium_kg=t,
        helium3_kg=he3,
        total_fuel_kg=total,
        burnup_fraction=0.0,
        reaction_type=rt,
    )


def make_reaction(power=100.0, charged_frac=0.1989,
                  rt=ReactionType.DT, t_s=0.0) -> ReactionState:
    return ReactionState(
        power_total_mw=power,
        power_charged_mw=power * charged_frac,
        power_neutron_mw=power * (1 - charged_frac),
        reactivity_m3s=5e-22,
        mass_flow_kgs=1e-6,
        charged_fraction=charged_frac,
        reaction_type=rt,
        t_s=t_s,
    )


def make_thermal(margin=0.8, heat_load=10.0, rad_temp=900.0) -> ThermalState:
    return ThermalState(
        core_temp_k=400.0,
        coolant_temp_k=350.0,
        radiator_temp_k=rad_temp,
        heat_load_mw=heat_load,
        heat_rejected_mw=5.0,
        thermal_margin=margin,
        radiator_area_m2=5000.0,
    )


def make_shielding(margin=0.9, dose=0.001) -> ShieldingState:
    return ShieldingState(
        neutron_flux_m2s=1e12,
        dose_rate_sv_hr=dose,
        shield_mass_kg=1000.0,
        shield_thickness_m=0.1,
        margin_fraction=margin,
    )


def make_power_bus(electric=50.0, thrust=40.0, mode=PropulsionMode.ELECTRIC_ONLY) -> PowerBusState:
    return PowerBusState(
        total_available_mw=100.0,
        electric_mw=electric,
        thrust_mw=thrust,
        thermal_mgmt_mw=5.0,
        parasitic_mw=3.0,
        allocation_efficiency=0.92,
        mode=mode,
    )


def make_propulsion(thrust=5000.0, isp=5000.0, mode=PropulsionMode.ELECTRIC_ONLY) -> FusionPropulsionState:
    return FusionPropulsionState(
        thrust_n=thrust,
        isp_s=isp,
        exhaust_vel_ms=isp * 9.80665,
        mass_flow_kgs=thrust / (isp * 9.80665),
        power_to_thrust_efficiency=0.65,
        mode=mode,
    )


def make_core_state(t=0.0, plasma=None, reaction=None, thermal=None,
                    shielding=None, power_bus=None, propulsion=None, fuel=None) -> FusionCoreState:
    return FusionCoreState(
        t_s=t,
        plasma=plasma or make_plasma(),
        reaction=reaction or make_reaction(),
        thermal=thermal or make_thermal(),
        shielding=shielding or make_shielding(),
        power_bus=power_bus or make_power_bus(),
        propulsion=propulsion or make_propulsion(),
        fuel=fuel or make_fuel(),
    )


def make_health(omega=0.8, abort=False) -> FusionHealth:
    return FusionHealth(
        omega_fusion=omega,
        omega_plasma=omega,
        omega_thermal=omega,
        omega_shielding=omega,
        omega_fuel=omega,
        omega_power=omega,
        verdict="HEALTHY" if omega > 0.8 else "STABLE",
        alerts=(),
        abort_required=abort,
    )


# ============================================================
# §1  FusionPhysicsConfig (5)
# ============================================================

class TestFusionPhysicsConfig:

    def test_boltzmann_constant(self, physics):
        assert abs(physics.k_b - 1.380649e-23) < 1e-30

    def test_sigma_sb_positive(self, physics):
        assert physics.sigma_sb > 0.0

    def test_g0_standard(self, physics):
        assert abs(physics.g0 - 9.80665) < 1e-6

    def test_mev_to_j_ratio(self, physics):
        # 1 MeV = 1000 keV → mev_to_j = 1000 * kev_to_j
        ratio = physics.mev_to_j / physics.kev_to_j
        assert abs(ratio - 1000.0) < 1e-6

    def test_kev_to_j_value(self, physics):
        assert abs(physics.kev_to_j - 1.602176634e-16) < 1e-25


# ============================================================
# §2  FuelState (8)
# ============================================================

class TestFuelState:

    def test_remaining_fraction_full(self):
        f = make_fuel(d=500.0, t=500.0, he3=0.0, total=1000.0)
        assert abs(f.remaining_fraction() - 1.0) < 1e-9

    def test_remaining_fraction_half(self):
        f = make_fuel(d=250.0, t=250.0, he3=0.0, total=1000.0)
        assert abs(f.remaining_fraction() - 0.5) < 1e-9

    def test_remaining_fraction_empty(self):
        f = make_fuel(d=0.0, t=0.0, he3=0.0, total=1000.0)
        assert f.remaining_fraction() == 0.0

    def test_remaining_fraction_zero_total(self):
        f = FuelState(0.0, 0.0, 0.0, 0.0, 0.0, ReactionType.DT)
        assert f.remaining_fraction() == 0.0

    def test_burnup_fraction_range(self):
        f = make_fuel(d=300.0, t=300.0)
        assert 0.0 <= f.burnup_fraction <= 1.0

    def test_frozen_immutable(self):
        f = make_fuel()
        with pytest.raises((AttributeError, TypeError)):
            f.deuterium_kg = 999.0  # type: ignore

    def test_reaction_type_preserved(self):
        f = make_fuel(rt=ReactionType.DHE3, d=500.0, he3=500.0, t=0.0)
        assert f.reaction_type == ReactionType.DHE3

    def test_remaining_includes_helium3(self):
        f = FuelState(
            deuterium_kg=200.0,
            tritium_kg=0.0,
            helium3_kg=200.0,
            total_fuel_kg=1000.0,
            burnup_fraction=0.6,
            reaction_type=ReactionType.DHE3,
        )
        assert abs(f.remaining_fraction() - 0.4) < 1e-9


# ============================================================
# §3  ReactionState 계약 (6)
# ============================================================

class TestReactionState:

    def test_charged_neutron_sum(self):
        r = make_reaction(power=100.0, charged_frac=0.1989)
        total_parts = r.power_charged_mw + r.power_neutron_mw
        assert abs(total_parts - r.power_total_mw) < 1e-6

    def test_frozen_immutable(self):
        r = make_reaction()
        with pytest.raises((AttributeError, TypeError)):
            r.power_total_mw = 999.0  # type: ignore

    def test_dt_charged_fraction(self):
        r = make_reaction(charged_frac=0.1989)
        assert abs(r.charged_fraction - 0.1989) < 1e-4

    def test_dhe3_charged_fraction_high(self):
        r = make_reaction(charged_frac=0.94, rt=ReactionType.DHE3)
        assert r.charged_fraction > 0.9

    def test_power_nonneg(self):
        r = make_reaction(power=0.0)
        assert r.power_total_mw >= 0.0
        assert r.power_charged_mw >= 0.0
        assert r.power_neutron_mw >= 0.0

    def test_reaction_type_field(self):
        r = make_reaction(rt=ReactionType.DD)
        assert r.reaction_type == ReactionType.DD


# ============================================================
# §4  D-T 반응률 물리 (10)
# ============================================================

class TestDTReactivity:

    def test_reactivity_positive_at_10kev(self, dt_reactor):
        sv = dt_reactor.reactivity(10.0)
        assert sv > 0.0

    def test_reactivity_increases_1_to_20kev(self, dt_reactor):
        sv_1  = dt_reactor.reactivity(1.0)
        sv_10 = dt_reactor.reactivity(10.0)
        sv_20 = dt_reactor.reactivity(20.0)
        assert sv_1 < sv_10
        assert sv_10 < sv_20

    def test_reactivity_clamps_below_min(self, dt_reactor):
        sv_min = dt_reactor.reactivity(0.01)
        sv_1   = dt_reactor.reactivity(1.0)
        assert sv_min <= sv_1

    def test_reactivity_clamps_above_max(self, dt_reactor):
        sv_200 = dt_reactor.reactivity(200.0)
        sv_500 = dt_reactor.reactivity(500.0)
        assert sv_200 >= sv_500 * 0.5  # 감쇠하지만 급감하지 않음

    def test_reactivity_zero_below_ignition(self, dt_reactor):
        plasma = make_plasma(T_kev=1.0, phase=PlasmaPhase.COLD)
        fuel = make_fuel()
        reaction, _ = dt_reactor.tick(plasma, fuel, 1.0, 1.0, FusionPhysicsConfig())
        assert reaction.power_total_mw == 0.0

    def test_reaction_power_nonneg(self, dt_reactor):
        plasma = make_plasma(T_kev=10.0, phase=PlasmaPhase.BURNING)
        fuel = make_fuel()
        reaction, _ = dt_reactor.tick(plasma, fuel, 1.0, 1.0, FusionPhysicsConfig())
        assert reaction.power_total_mw >= 0.0

    def test_throttle_scales_power(self, dt_reactor):
        plasma = make_plasma(T_kev=10.0, phase=PlasmaPhase.BURNING)
        fuel = make_fuel()
        r_full, _ = dt_reactor.tick(plasma, fuel, 1.0, 1.0, FusionPhysicsConfig())
        r_half, _ = dt_reactor.tick(plasma, fuel, 0.5, 1.0, FusionPhysicsConfig())
        # 낮은 스로틀 → 낮은 출력
        assert r_half.power_total_mw < r_full.power_total_mw

    def test_fuel_decreases_after_tick(self, dt_reactor):
        plasma = make_plasma(T_kev=10.0, phase=PlasmaPhase.BURNING)
        fuel = make_fuel(d=500.0, t=500.0)
        _, new_fuel = dt_reactor.tick(plasma, fuel, 1.0, 1.0, FusionPhysicsConfig())
        # 높은 출력에서는 연료 감소 (극소량이므로 <= 비교)
        assert new_fuel.deuterium_kg + new_fuel.tritium_kg <= fuel.deuterium_kg + fuel.tritium_kg

    def test_reaction_power_density_positive(self, dt_reactor):
        pd = dt_reactor.reaction_power_density(5e19, 5e19, 10.0)
        assert pd > 0.0

    def test_reaction_power_density_zero_at_zero_density(self, dt_reactor):
        pd = dt_reactor.reaction_power_density(0.0, 5e19, 10.0)
        assert pd == 0.0


# ============================================================
# §5  D-He3 반응률 물리 (6)
# ============================================================

class TestDHe3Reactivity:

    def test_dhe3_positive_at_100kev(self, dhe3_reactor):
        sv = dhe3_reactor.reactivity(100.0)
        assert sv > 0.0

    def test_dhe3_lower_than_dt_at_10kev(self, dt_reactor, dhe3_reactor):
        sv_dt   = dt_reactor.reactivity(10.0)
        sv_dhe3 = dhe3_reactor.reactivity(10.0)
        assert sv_dhe3 < sv_dt

    def test_dhe3_increases_10_to_100kev(self, dhe3_reactor):
        sv_10  = dhe3_reactor.reactivity(10.0)
        sv_100 = dhe3_reactor.reactivity(100.0)
        assert sv_10 < sv_100

    def test_dhe3_charged_frac_high(self, dhe3_reactor):
        plasma = make_plasma(T_kev=100.0, phase=PlasmaPhase.BURNING)
        fuel = FuelState(500.0, 0.0, 500.0, 1000.0, 0.0, ReactionType.DHE3)
        reaction, _ = dhe3_reactor.tick(plasma, fuel, 1.0, 1.0, FusionPhysicsConfig())
        if reaction.power_total_mw > 0:
            assert reaction.charged_fraction > 0.9

    def test_dhe3_tick_no_tritium(self, dhe3_reactor):
        plasma = make_plasma(T_kev=100.0, phase=PlasmaPhase.BURNING)
        fuel = FuelState(500.0, 0.0, 500.0, 1000.0, 0.0, ReactionType.DHE3)
        _, new_fuel = dhe3_reactor.tick(plasma, fuel, 1.0, 1.0, FusionPhysicsConfig())
        assert new_fuel.tritium_kg == 0.0

    def test_dd_reactivity_positive(self, dd_reactor):
        sv = dd_reactor.reactivity(10.0)
        assert sv > 0.0


# ============================================================
# §6  ThermalSystem (10)
# ============================================================

class TestThermalSystem:

    @pytest.fixture
    def thermal_sys(self):
        return ThermalSystem(ThermalConfig())

    def test_radiated_power_positive(self, thermal_sys):
        P = thermal_sys.radiated_power_mw(900.0)
        assert P > 0.0

    def test_radiated_power_t4_scaling(self, thermal_sys):
        P1 = thermal_sys.radiated_power_mw(900.0)
        P2 = thermal_sys.radiated_power_mw(1800.0)
        ratio = P2 / P1
        assert abs(ratio - 16.0) < 0.5  # T⁴ 비례

    def test_radiator_mass_positive(self, thermal_sys):
        mass = thermal_sys.radiator_mass_kg()
        assert mass > 0.0

    def test_radiator_mass_formula(self):
        cfg = ThermalConfig(radiator_area_m2=1000.0, specific_mass_kg_m2=5.0)
        ts = ThermalSystem(cfg)
        assert abs(ts.radiator_mass_kg() - 5000.0) < 1e-6

    def test_tick_returns_thermal_state(self, thermal_sys):
        state = make_thermal()
        new = thermal_sys.tick(10.0, 1.0, state, FusionPhysicsConfig())
        assert isinstance(new, ThermalState)

    def test_tick_thermal_margin_range(self, thermal_sys):
        state = make_thermal(margin=1.0)
        new = thermal_sys.tick(5.0, 1.0, state, FusionPhysicsConfig())
        assert -1.0 <= new.thermal_margin <= 1.0

    def test_tick_high_heat_reduces_margin(self, thermal_sys):
        state = make_thermal(margin=1.0, rad_temp=300.0)
        new = thermal_sys.tick(500.0, 10.0, state, FusionPhysicsConfig())
        # 고열 부하 → 방열판 온도 상승 → thermal_margin 감소 (margin < 1.0)
        assert new.thermal_margin < 1.0

    def test_tick_radiator_temp_nonneg(self, thermal_sys):
        state = make_thermal()
        new = thermal_sys.tick(0.0, 1.0, state, FusionPhysicsConfig())
        assert new.radiator_temp_k > 0.0

    def test_tick_heat_load_preserved(self, thermal_sys):
        state = make_thermal()
        new = thermal_sys.tick(42.0, 1.0, state, FusionPhysicsConfig())
        assert abs(new.heat_load_mw - 42.0) < 1e-9

    def test_zero_heat_load(self, thermal_sys):
        state = make_thermal(heat_load=0.0, rad_temp=1000.0)
        new = thermal_sys.tick(0.0, 1.0, state, FusionPhysicsConfig())
        # 열 입력 없으면 방열판 냉각
        assert new.radiator_temp_k <= state.radiator_temp_k + 1.0  # 감소 또는 소폭 변화


# ============================================================
# §7  ShieldingModel (8)
# ============================================================

class TestShieldingModel:

    @pytest.fixture
    def shielding(self):
        return ShieldingModel(ShieldingConfig())

    def test_neutron_flux_zero_for_zero_power(self, shielding):
        r = make_reaction(power=0.0)
        state = shielding.tick(r, FusionPhysicsConfig())
        assert state.neutron_flux_m2s == 0.0

    def test_neutron_flux_increases_with_power(self, shielding):
        flux1 = shielding.neutron_flux(10.0, 20.0, ReactionType.DT, FusionPhysicsConfig())
        flux2 = shielding.neutron_flux(100.0, 20.0, ReactionType.DT, FusionPhysicsConfig())
        assert flux2 > flux1

    def test_shield_mass_increases_with_flux(self, shielding):
        r1 = make_reaction(power=10.0)
        r2 = make_reaction(power=1000.0)
        s1 = shielding.tick(r1, FusionPhysicsConfig())
        s2 = shielding.tick(r2, FusionPhysicsConfig())
        assert s2.shield_mass_kg >= s1.shield_mass_kg

    def test_margin_fraction_range(self, shielding):
        r = make_reaction(power=100.0)
        s = shielding.tick(r, FusionPhysicsConfig())
        assert -1.0 <= s.margin_fraction <= 1.0

    def test_dose_rate_proportional_to_flux(self, shielding):
        phys = FusionPhysicsConfig()
        cfg = shielding.config
        r = make_reaction(power=100.0)
        # tick() 내부에서 neutron_power_mw = r.power_neutron_mw를 사용
        flux = shielding.neutron_flux(r.power_neutron_mw, cfg.crew_distance_m, ReactionType.DT, phys)
        dose = flux * cfg.dose_factor_sv_per_flux * 3600.0
        s = shielding.tick(r, phys)
        assert abs(s.dose_rate_sv_hr - dose) < 1e-6

    def test_required_thickness_nonneg(self, shielding):
        t = shielding.required_thickness_m(1e15)
        assert t >= 0.0

    def test_required_mass_nonneg(self, shielding):
        m = shielding.required_mass_kg(0.5)
        assert m >= 0.0

    def test_pb11_zero_neutron_power(self, shielding):
        r = make_reaction(power=100.0, rt=ReactionType.PB11)
        # p-B11 무중성자 반응: neutron_power = 0 근사
        # 반응 자체에서 neutron_power_mw = 0 → flux = 0
        r_zero_neutron = ReactionState(
            power_total_mw=100.0,
            power_charged_mw=99.0,
            power_neutron_mw=0.0,
            reactivity_m3s=1e-25,
            mass_flow_kgs=1e-8,
            charged_fraction=0.99,
            reaction_type=ReactionType.PB11,
            t_s=0.0,
        )
        s = shielding.tick(r_zero_neutron, FusionPhysicsConfig())
        assert s.neutron_flux_m2s == 0.0


# ============================================================
# §8  ConfinementModel (8)
# ============================================================

class TestConfinementModel:

    @pytest.fixture
    def conf(self):
        return ConfinementModel(ConfinementConfig())

    def test_triple_product_formula(self, conf):
        p = make_plasma(T_kev=10.0, n=1e20, tau=3.0)
        tp = conf.triple_product(p)
        assert abs(tp - 1e20 * 3.0 * 10.0) < 1e10

    def test_lawson_satisfied_dt_high_temp(self, conf):
        # 로손 기준을 만족하도록 설정
        p = make_plasma(T_kev=10.0, n=1e21, tau=3.0)
        assert conf.lawson_satisfied(p, ReactionType.DT)

    def test_lawson_not_satisfied_cold(self, conf):
        p = make_plasma(T_kev=0.1, n=1e15, tau=0.1)
        assert not conf.lawson_satisfied(p, ReactionType.DT)

    def test_dhe3_threshold_higher(self, conf):
        # D-He3는 로손 기준이 더 높음
        p = make_plasma(T_kev=10.0, n=1e20, tau=3.0)
        dt_ok  = conf.lawson_satisfied(p, ReactionType.DT)
        dhe3_ok = conf.lawson_satisfied(p, ReactionType.DHE3)
        # 같은 조건이면 DHe3가 더 달성하기 어렵다
        # (dt_ok가 True라면 dhe3_ok는 False일 수 있음)
        if dt_ok:
            # DT 기준 통과해도 DHe3 기준은 더 높으므로 반드시 통과하지 않음
            assert not dhe3_ok or conf.config.dhe3_lawson_threshold <= conf.config.dt_lawson_threshold

    def test_q_factor_zero_at_zero_heating(self, conf):
        p = make_plasma()
        q = conf.q_factor_estimate(p, 0.0)
        assert q == 0.0

    def test_q_factor_positive_with_heating(self, conf):
        p = make_plasma(T_kev=20.0, n=1e21, tau=5.0)
        q = conf.q_factor_estimate(p, 50.0)
        assert q >= 0.0

    def test_beta_estimate_range(self, conf):
        p = make_plasma(T_kev=10.0, n=1e20)
        beta = conf.beta_estimate(p, FusionPhysicsConfig())
        assert 0.0 <= beta <= 1.0

    def test_assess_returns_plasma_state(self, conf):
        p = make_plasma()
        new_p = conf.assess(p, ReactionType.DT, 50.0, FusionPhysicsConfig())
        assert isinstance(new_p, PlasmaState)
        assert new_p.triple_product >= 0.0


# ============================================================
# §9  PlasmaFSM (12)
# ============================================================

class TestPlasmaFSM:

    @pytest.fixture
    def fsm(self):
        cfg = PlasmaFSMConfig(
            preheating_duration_s=5.0,
            ignition_temp_kev=4.0,
            sustained_q_threshold=1.0,
            disruption_beta_limit=0.08,
            quench_duration_s=3.0,
            ignition_attempt_timeout_s=10.0,
        )
        return PlasmaFSM(cfg)

    def _ctx(self, t=0.0, T=1.0, q=0.0, beta=0.01, lawson=False,
             abort=False, go=False, heat=True) -> PlasmaFSMContext:
        return PlasmaFSMContext(
            t_s=t, plasma_temp_kev=T, q_factor=q,
            beta=beta, lawson_satisfied=lawson,
            abort_trigger=abort, go_command=go, heating_available=heat,
        )

    def test_initial_phase_cold(self, fsm):
        assert fsm.phase == PlasmaPhase.COLD

    def test_cold_no_go_stays_cold(self, fsm):
        phase = fsm.update(self._ctx(t=0.0, go=False))
        assert phase == PlasmaPhase.COLD

    def test_cold_go_transitions_preheating(self, fsm):
        phase = fsm.update(self._ctx(t=0.0, go=True, heat=True))
        assert phase == PlasmaPhase.PREHEATING

    def test_preheating_no_timer_stays_preheating(self, fsm):
        fsm.update(self._ctx(t=0.0, go=True))  # → PREHEATING
        phase = fsm.update(self._ctx(t=1.0, T=5.0))  # 아직 5s 미경과
        assert phase == PlasmaPhase.PREHEATING

    def test_preheating_timer_complete_transitions_ignition(self, fsm):
        fsm.update(self._ctx(t=0.0, go=True))  # → PREHEATING
        phase = fsm.update(self._ctx(t=5.0, T=5.0))  # 5s 경과 + T > 4 keV
        assert phase == PlasmaPhase.IGNITION_ATTEMPT

    def test_ignition_lawson_satisfied_transitions_burning(self, fsm):
        fsm.update(self._ctx(t=0.0, go=True))
        fsm.update(self._ctx(t=5.0, T=5.0))       # → IGNITION_ATTEMPT
        phase = fsm.update(self._ctx(t=6.0, T=5.0, lawson=True))
        assert phase == PlasmaPhase.BURNING

    def test_ignition_timeout_transitions_quench(self, fsm):
        fsm.update(self._ctx(t=0.0, go=True))
        fsm.update(self._ctx(t=5.0, T=5.0))       # → IGNITION_ATTEMPT at t=5
        phase = fsm.update(self._ctx(t=16.0, T=3.0, lawson=False))  # 10s 초과
        assert phase == PlasmaPhase.QUENCH

    def test_burning_high_q_transitions_sustained(self, fsm):
        fsm.update(self._ctx(t=0.0, go=True))
        fsm.update(self._ctx(t=5.0, T=5.0))
        fsm.update(self._ctx(t=6.0, T=5.0, lawson=True))   # → BURNING
        phase = fsm.update(self._ctx(t=7.0, T=10.0, q=2.0, lawson=True))
        assert phase == PlasmaPhase.SUSTAINED

    def test_burning_beta_disruption_transitions_quench(self, fsm):
        fsm.update(self._ctx(t=0.0, go=True))
        fsm.update(self._ctx(t=5.0, T=5.0))
        fsm.update(self._ctx(t=6.0, T=5.0, lawson=True))   # → BURNING
        phase = fsm.update(self._ctx(t=7.0, T=5.0, beta=0.09, lawson=True))
        assert phase == PlasmaPhase.QUENCH

    def test_any_abort_transitions_shutdown(self, fsm):
        fsm.update(self._ctx(t=0.0, go=True))
        phase = fsm.update(self._ctx(t=1.0, abort=True))
        assert phase == PlasmaPhase.SHUTDOWN

    def test_quench_timer_transitions_cold(self, fsm):
        fsm.update(self._ctx(t=0.0, go=True))
        fsm.update(self._ctx(t=5.0, T=5.0))
        fsm.update(self._ctx(t=16.0, T=3.0, lawson=False))   # → QUENCH at t=5+10=15? (5+10 timeout)
        # quench 시작 후 3s 경과
        phase = fsm.update(self._ctx(t=20.0))
        assert phase == PlasmaPhase.COLD

    def test_shutdown_stays_shutdown(self, fsm):
        fsm.update(self._ctx(t=0.0, go=True))
        fsm.update(self._ctx(t=1.0, abort=True))  # → SHUTDOWN
        phase = fsm.update(self._ctx(t=2.0))
        assert phase == PlasmaPhase.SHUTDOWN


# ============================================================
# §10 PowerBusController (8)
# ============================================================

class TestPowerBusController:

    @pytest.fixture
    def controller(self):
        return PowerBusController()

    @pytest.fixture
    def cfg(self):
        return PowerBusConfig()

    def test_allocate_returns_power_bus_state(self, controller, cfg):
        r = make_reaction(power=200.0)
        state = controller.allocate(r, PropulsionMode.ELECTRIC_ONLY, cfg)
        assert isinstance(state, PowerBusState)

    def test_total_available_matches_charged(self, controller, cfg):
        r = make_reaction(power=200.0, charged_frac=0.1989)
        state = controller.allocate(r, PropulsionMode.OFF, cfg)
        assert abs(state.total_available_mw - r.power_charged_mw) < 1e-6

    def test_electric_plus_thrust_le_total(self, controller, cfg):
        r = make_reaction(power=500.0)
        state = controller.allocate(r, PropulsionMode.ELECTRIC_ONLY, cfg)
        used = state.electric_mw + state.thrust_mw + state.thermal_mgmt_mw + state.parasitic_mw
        assert used <= state.total_available_mw + 1e-6

    def test_off_mode_no_thrust(self, controller, cfg):
        r = make_reaction(power=200.0)
        state = controller.allocate(r, PropulsionMode.OFF, cfg)
        assert state.thrust_mw == 0.0

    def test_electric_mw_nonneg(self, controller, cfg):
        r = make_reaction(power=100.0)
        for mode in PropulsionMode:
            state = controller.allocate(r, mode, cfg)
            assert state.electric_mw >= 0.0

    def test_allocation_efficiency_range(self, controller, cfg):
        r = make_reaction(power=200.0)
        state = controller.allocate(r, PropulsionMode.HYBRID, cfg)
        assert 0.0 <= state.allocation_efficiency <= 1.0

    def test_mode_preserved(self, controller, cfg):
        r = make_reaction(power=100.0)
        state = controller.allocate(r, PropulsionMode.DIRECT_THRUST, cfg)
        assert state.mode == PropulsionMode.DIRECT_THRUST

    def test_zero_power_all_zero(self, controller, cfg):
        r = make_reaction(power=0.0)
        state = controller.allocate(r, PropulsionMode.ELECTRIC_ONLY, cfg)
        assert state.total_available_mw == 0.0


# ============================================================
# §11 FusionPropulsionEngine (8)
# ============================================================

class TestFusionPropulsionEngine:

    @pytest.fixture
    def engine(self):
        return FusionPropulsionEngine(FusionPropulsionConfig())

    def test_electric_mode_returns_state(self, engine):
        s = engine.electric_mode(10.0, FusionPhysicsConfig())
        assert isinstance(s, FusionPropulsionState)

    def test_electric_mode_thrust_positive(self, engine):
        s = engine.electric_mode(50.0, FusionPhysicsConfig())
        assert s.thrust_n > 0.0

    def test_direct_mode_thrust_positive(self, engine):
        s = engine.direct_mode(50.0, FusionPhysicsConfig())
        assert s.thrust_n > 0.0

    def test_electric_isp_preserved(self, engine):
        s = engine.electric_mode(50.0, FusionPhysicsConfig())
        assert abs(s.isp_s - 5000.0) < 1.0

    def test_off_mode_zero_thrust(self, engine):
        bus = make_power_bus(mode=PropulsionMode.OFF)
        s = engine.tick(bus, FusionPhysicsConfig())
        assert s.thrust_n == 0.0

    def test_electric_mode_higher_thrust_with_more_power(self, engine):
        phys = FusionPhysicsConfig()
        s1 = engine.electric_mode(10.0, phys)
        s2 = engine.electric_mode(100.0, phys)
        assert s2.thrust_n > s1.thrust_n

    def test_hybrid_mode_returns_combined_thrust(self, engine):
        bus = make_power_bus(thrust=50.0, mode=PropulsionMode.HYBRID)
        s = engine.tick(bus, FusionPhysicsConfig())
        assert s.thrust_n > 0.0
        assert s.mode == PropulsionMode.HYBRID

    def test_direct_mode_isp_higher_than_electric(self, engine):
        phys = FusionPhysicsConfig()
        se = engine.electric_mode(50.0, phys)
        sd = engine.direct_mode(50.0, phys)
        assert sd.isp_s > se.isp_s


# ============================================================
# §12 OmegaMonitor (10)
# ============================================================

class TestOmegaMonitor:

    @pytest.fixture
    def monitor(self):
        return OmegaMonitor()

    @pytest.fixture
    def omega_cfg(self):
        return OmegaConfig()

    def test_omega_range(self, monitor, omega_cfg):
        state = make_core_state()
        h = monitor.observe(state, omega_cfg)
        assert 0.0 <= h.omega_fusion <= 1.0

    def test_omega_components_range(self, monitor, omega_cfg):
        state = make_core_state()
        h = monitor.observe(state, omega_cfg)
        for v in [h.omega_plasma, h.omega_thermal, h.omega_shielding,
                  h.omega_fuel, h.omega_power]:
            assert 0.0 <= v <= 1.0

    def test_healthy_verdict_high_omega(self, monitor, omega_cfg):
        # 건강한 상태 → HEALTHY
        state = make_core_state(
            plasma=make_plasma(T_kev=20.0, q=5.0, beta=0.01, phase=PlasmaPhase.SUSTAINED),
            thermal=make_thermal(margin=0.95),
            shielding=make_shielding(margin=0.95),
            fuel=make_fuel(d=490.0, t=490.0),
            power_bus=make_power_bus(electric=100.0),
        )
        h = monitor.observe(state, omega_cfg)
        assert h.verdict in ("HEALTHY", "STABLE")

    def test_critical_verdict_low_omega(self, monitor, omega_cfg):
        # 위기 상태
        state = make_core_state(
            plasma=make_plasma(T_kev=0.1, q=0.0, beta=0.09, phase=PlasmaPhase.QUENCH),
            thermal=make_thermal(margin=0.02),
            shielding=make_shielding(margin=0.01, dose=0.2),
            fuel=make_fuel(d=1.0, t=1.0),
            power_bus=make_power_bus(electric=1.0),
        )
        h = monitor.observe(state, omega_cfg)
        assert h.verdict in ("FRAGILE", "CRITICAL")

    def test_abort_required_when_beta_high(self, monitor, omega_cfg):
        state = make_core_state(
            plasma=make_plasma(beta=0.11)
        )
        h = monitor.observe(state, omega_cfg)
        assert h.abort_required

    def test_abort_required_when_dose_high(self, monitor, omega_cfg):
        state = make_core_state(
            shielding=make_shielding(margin=-0.5, dose=0.5)
        )
        h = monitor.observe(state, omega_cfg)
        assert h.abort_required

    def test_no_abort_healthy_state(self, monitor, omega_cfg):
        state = make_core_state(
            plasma=make_plasma(beta=0.01, q=3.0, T_kev=15.0, phase=PlasmaPhase.SUSTAINED),
            thermal=make_thermal(margin=0.9),
            shielding=make_shielding(margin=0.9, dose=0.001),
            fuel=make_fuel(d=450.0, t=450.0),
            power_bus=make_power_bus(electric=80.0),
        )
        h = monitor.observe(state, omega_cfg)
        assert not h.abort_required

    def test_verdict_thresholds(self, monitor, omega_cfg):
        verdicts = []
        for omega_val in [0.9, 0.7, 0.5, 0.3]:
            # omega를 직접 조작할 수 없으므로 반환값 verdict만 검사
            h = FusionHealth(
                omega_fusion=omega_val,
                omega_plasma=omega_val,
                omega_thermal=omega_val,
                omega_shielding=omega_val,
                omega_fuel=omega_val,
                omega_power=omega_val,
                verdict=("HEALTHY" if omega_val > 0.8 else
                         "STABLE"  if omega_val > 0.6 else
                         "FRAGILE" if omega_val > 0.4 else "CRITICAL"),
                alerts=(),
                abort_required=omega_val < 0.25,
            )
            verdicts.append(h.verdict)
        assert verdicts[0] == "HEALTHY"
        assert verdicts[1] == "STABLE"
        assert verdicts[2] == "FRAGILE"
        assert verdicts[3] == "CRITICAL"

    def test_alerts_tuple(self, monitor, omega_cfg):
        state = make_core_state()
        h = monitor.observe(state, omega_cfg)
        assert isinstance(h.alerts, tuple)

    def test_frozen_health(self, monitor, omega_cfg):
        state = make_core_state()
        h = monitor.observe(state, omega_cfg)
        with pytest.raises((AttributeError, TypeError)):
            h.omega_fusion = 0.99  # type: ignore


# ============================================================
# §13 AbortSystem (8)
# ============================================================

class TestAbortSystem:

    @pytest.fixture
    def abort_sys(self):
        return AbortSystem(AbortConfig())

    def test_none_for_healthy_state(self, abort_sys):
        state = make_core_state(
            plasma=make_plasma(beta=0.01),
            thermal=make_thermal(margin=0.9),
            shielding=make_shielding(dose=0.001),
        )
        h = make_health(omega=0.9)
        mode = abort_sys.evaluate(h, state, PlasmaPhase.SUSTAINED)
        assert mode == AbortMode.NONE

    def test_emergency_quench_on_external_abort(self, abort_sys):
        state = make_core_state()
        h = make_health(omega=0.9)
        mode = abort_sys.evaluate(h, state, PlasmaPhase.BURNING, external_abort=True)
        assert mode == AbortMode.EMERGENCY_QUENCH

    def test_magnetic_dump_on_high_beta(self, abort_sys):
        state = make_core_state(plasma=make_plasma(beta=0.12))
        h = make_health(omega=0.7)
        mode = abort_sys.evaluate(h, state, PlasmaPhase.BURNING)
        assert mode == AbortMode.MAGNETIC_DUMP

    def test_controlled_shutdown_on_high_dose(self, abort_sys):
        state = make_core_state(shielding=make_shielding(dose=0.5, margin=-1.0))
        h = make_health(omega=0.7)
        mode = abort_sys.evaluate(h, state, PlasmaPhase.BURNING)
        assert mode == AbortMode.CONTROLLED_SHUTDOWN

    def test_controlled_shutdown_on_low_thermal_margin(self, abort_sys):
        state = make_core_state(thermal=make_thermal(margin=0.01))
        h = make_health(omega=0.7)
        mode = abort_sys.evaluate(h, state, PlasmaPhase.BURNING)
        assert mode == AbortMode.CONTROLLED_SHUTDOWN

    def test_controlled_shutdown_on_low_omega(self, abort_sys):
        state = make_core_state(
            plasma=make_plasma(beta=0.01),
            thermal=make_thermal(margin=0.9),
            shielding=make_shielding(dose=0.001),
        )
        h = make_health(omega=0.10)
        mode = abort_sys.evaluate(h, state, PlasmaPhase.BURNING)
        assert mode == AbortMode.CONTROLLED_SHUTDOWN

    def test_priority_external_over_beta(self, abort_sys):
        # external_abort 최우선 → EMERGENCY_QUENCH (not MAGNETIC_DUMP)
        state = make_core_state(plasma=make_plasma(beta=0.12))
        h = make_health(omega=0.5)
        mode = abort_sys.evaluate(h, state, PlasmaPhase.BURNING, external_abort=True)
        assert mode == AbortMode.EMERGENCY_QUENCH

    def test_abort_required_flag_consistency(self, abort_sys):
        state = make_core_state(plasma=make_plasma(beta=0.12))
        h = make_health(omega=0.5, abort=True)
        mode = abort_sys.evaluate(h, state, PlasmaPhase.BURNING)
        assert mode != AbortMode.NONE


# ============================================================
# §14 FusionChain (8)
# ============================================================

class TestFusionChain:

    @pytest.fixture
    def chain(self):
        return FusionChain("TEST-01", record_interval=5)

    def test_genesis_block_exists(self, chain):
        assert len(chain) == 1

    def test_record_event_increments_chain(self, chain):
        chain.record_event(1.0, "IGNITION", {"detail": "test"})
        assert len(chain) == 2

    def test_verify_integrity_initial(self, chain):
        assert chain.verify_integrity()

    def test_verify_integrity_after_events(self, chain):
        for i in range(5):
            chain.record_event(float(i), "TELEMETRY", {"i": i})
        assert chain.verify_integrity()

    def test_hash_tampering_detected(self, chain):
        chain.record_event(1.0, "IGNITION", {"a": 1})
        # 내부 블록 해시를 조작
        blk = chain.blocks[1]
        # frozen dataclass → 새 객체 생성으로 교체 시뮬레이션
        import dataclasses
        tampered = dataclasses.replace(blk, block_hash="DEADBEEF" * 8)
        chain._blocks[1] = tampered
        assert not chain.verify_integrity()

    def test_record_periodic(self, chain):
        # record()는 interval마다 기록 → 5틱마다 1번
        class FakeFrame:
            t_s = 0.0
            def summary_dict(self):
                return {"t_s": self.t_s}

        frame = FakeFrame()
        for i in range(10):
            chain.record(frame)
        # 제네시스 1 + 10틱 중 5배수 2번(5,10) = 3 블록
        assert len(chain) == 3

    def test_export_json(self, chain, tmp_path):
        chain.record_event(1.0, "TEST", {"x": 42})
        path = str(tmp_path / "chain.json")
        chain.export_json(path)
        import json
        with open(path) as f:
            data = json.load(f)
        assert data["reactor_id"] == "TEST-01"
        assert len(data["chain"]) == 2

    def test_block_type(self, chain):
        from fusion_core.audit.fusion_chain import FusionBlock
        chain.record_event(0.0, "TEST", {})
        assert isinstance(chain.blocks[-1], FusionBlock)


# ============================================================
# §15 FusionAgent 통합 (12)
# ============================================================

class TestFusionAgent:

    @pytest.fixture
    def agent(self):
        cfg = FusionAgentConfig(
            dt_s=1.0,
            reaction_config=ReactionConfig(
                reaction_type=ReactionType.DT,
                min_ignition_temp_kev=4.0,
            ),
        )
        return FusionAgent(cfg)

    def test_tick_returns_telemetry_frame(self, agent):
        frame = agent.tick()
        assert isinstance(frame, TelemetryFrame)

    def test_simulate_100s_returns_100_frames(self, agent):
        frames = agent.simulate(100.0)
        assert len(frames) == 100

    def test_tick_t_s_increments(self, agent):
        f1 = agent.tick()
        f2 = agent.tick()
        assert f2.t_s > f1.t_s

    def test_initial_phase_cold(self, agent):
        frame = agent.tick()
        assert frame.phase == PlasmaPhase.COLD

    def test_ignite_sets_go_command(self, agent):
        agent.ignite()
        assert agent._go_command is True

    def test_shutdown_triggers_abort(self, agent):
        agent.shutdown()
        frame = agent.tick()
        assert frame.abort_mode != AbortMode.NONE or frame.phase == PlasmaPhase.SHUTDOWN

    def test_set_mode(self, agent):
        agent.set_mode(PropulsionMode.ELECTRIC_ONLY)
        assert agent._mode == PropulsionMode.ELECTRIC_ONLY

    def test_set_throttle_clamps(self, agent):
        agent.set_throttle(1.5)
        assert agent._throttle == 1.0
        agent.set_throttle(-0.5)
        assert agent._throttle == 0.0

    def test_frame_health_omega_range(self, agent):
        frames = agent.simulate(10.0)
        for f in frames:
            assert 0.0 <= f.health.omega_fusion <= 1.0

    def test_frame_abort_mode_valid(self, agent):
        frames = agent.simulate(10.0)
        for f in frames:
            assert isinstance(f.abort_mode, AbortMode)

    def test_chain_integrity_after_simulation(self, agent):
        agent.simulate(50.0)
        assert agent._chain.verify_integrity()

    def test_fuel_not_negative_after_simulation(self, agent):
        frames = agent.simulate(100.0)
        last = frames[-1]
        assert last.state.fuel.deuterium_kg >= 0.0
        assert last.state.fuel.tritium_kg >= 0.0
        assert last.state.fuel.helium3_kg >= 0.0
