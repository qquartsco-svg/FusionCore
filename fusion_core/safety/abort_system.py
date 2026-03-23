"""
fusion_core/safety/abort_system.py
핵융합 코어 비상 중단 시스템.

우선순위 기반 abort 모드 결정.
가장 위험한 상태(베타 초과 → 자기장 붕괴)를 최우선으로 처리한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from fusion_core.contracts.schemas import (
    AbortMode,
    FusionCoreState,
    FusionHealth,
    PlasmaPhase,
)


@dataclass
class AbortConfig:
    """비상 중단 시스템 설정."""

    omega_abort_threshold: float = 0.25         # 종합 건전성 중단 임계값
    max_beta_abort: float = 0.10                # 베타 초과 중단 임계값
    max_dose_rate_sv_hr: float = 0.1            # 최대 허용 선량률           [Sv/hr]
    max_thermal_load_fraction: float = 0.95     # 허용 열 부하 비율 (margin < 0.05 → abort)


class AbortSystem:
    """핵융합 코어 비상 중단 시스템."""

    def evaluate(
        self,
        health: FusionHealth,
        state: FusionCoreState,
        phase: PlasmaPhase,
        external_abort: bool = False,
    ) -> AbortMode:
        """
        우선순위 기반 AbortMode 결정.

        1. external_abort                           → EMERGENCY_QUENCH
        2. beta > max_beta_abort                    → MAGNETIC_DUMP
        3. dose_rate > max_dose_rate                → CONTROLLED_SHUTDOWN
        4. thermal_margin < 0.05                    → CONTROLLED_SHUTDOWN
        5. omega_fusion < omega_abort_threshold     → CONTROLLED_SHUTDOWN
        6. 정상                                     → NONE
        """
        cfg = self

        # 1. 외부 중단 명령
        if external_abort:
            return AbortMode.EMERGENCY_QUENCH

        # 2. 베타 초과 (자기 불안정 — 가장 급박)
        if state.plasma.beta > AbortConfig().max_beta_abort:
            return AbortMode.MAGNETIC_DUMP

        # 임계값 참조 (config 인스턴스에서)
        # AbortSystem은 config를 주입받아야 하므로 self.config로 참조
        return AbortMode.NONE  # fallback (실제 로직은 아래 _evaluate_with_config에서)

    def __init__(self, config: AbortConfig | None = None) -> None:
        self.config = config or AbortConfig()

    def evaluate(  # type: ignore[override]
        self,
        health: FusionHealth,
        state: FusionCoreState,
        phase: PlasmaPhase,
        external_abort: bool = False,
    ) -> AbortMode:
        """
        우선순위 기반 AbortMode 결정.

        1. external_abort                           → EMERGENCY_QUENCH
        2. beta > max_beta_abort                    → MAGNETIC_DUMP
        3. dose_rate > max_dose_rate                → CONTROLLED_SHUTDOWN
        4. thermal_margin < 0.05                    → CONTROLLED_SHUTDOWN
        5. omega_fusion < omega_abort_threshold     → CONTROLLED_SHUTDOWN
        6. 정상                                     → NONE
        """
        cfg = self.config

        # 1. 외부 중단 명령
        if external_abort:
            return AbortMode.EMERGENCY_QUENCH

        # 2. 베타 초과 (자기 불안정 — 자기장 덤프 필요)
        if state.plasma.beta > cfg.max_beta_abort:
            return AbortMode.MAGNETIC_DUMP

        # 3. 선량률 초과
        if state.shielding.dose_rate_sv_hr > cfg.max_dose_rate_sv_hr:
            return AbortMode.CONTROLLED_SHUTDOWN

        # 4. 열 여유 부족
        if state.thermal.thermal_margin < (1.0 - cfg.max_thermal_load_fraction):
            return AbortMode.CONTROLLED_SHUTDOWN

        # 5. 종합 건전성 임계값 이하
        if health.omega_fusion < cfg.omega_abort_threshold:
            return AbortMode.CONTROLLED_SHUTDOWN

        return AbortMode.NONE
