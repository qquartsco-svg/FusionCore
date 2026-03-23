"""
fusion_core/plasma/plasma_fsm.py
플라즈마 생애주기 유한상태기계(FSM) 모듈.

동역학 시스템 철학: 상태는 관측된 궤적 위의 추정값이다.
전이 조건은 물리 임계값 기반이며, 타이머로 시간 의존 전이를 구현한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fusion_core.contracts.schemas import PlasmaPhase


@dataclass
class PlasmaFSMConfig:
    """플라즈마 FSM 설정."""

    preheating_duration_s: float = 30.0     # 예열 지속 시간             [s]
    ignition_temp_kev: float = 4.0          # 점화 임계 온도             [keV]
    sustained_q_threshold: float = 1.0      # 지속 연소 Q 기준
    disruption_beta_limit: float = 0.08     # 붕괴(disruption) 베타 한계
    quench_duration_s: float = 5.0          # quench 후 재시동 대기      [s]
    ignition_attempt_timeout_s: float = 60.0  # 점화 시도 최대 시간      [s]


@dataclass
class PlasmaFSMContext:
    """FSM 전이 평가에 필요한 관측값 묶음."""

    t_s: float
    plasma_temp_kev: float
    q_factor: float
    beta: float
    lawson_satisfied: bool
    abort_trigger: bool
    go_command: bool
    heating_available: bool


class PlasmaFSM:
    """
    플라즈마 위상 유한상태기계.

    상태 전이:
        COLD            → PREHEATING        : go_command & heating_available
        PREHEATING      → IGNITION_ATTEMPT  : T > ignition_temp & 예열 타이머 완료
        IGNITION_ATTEMPT → BURNING          : lawson_satisfied
        IGNITION_ATTEMPT → QUENCH           : 타이머 초과 & not lawson_satisfied
        BURNING         → SUSTAINED         : Q > sustained_q_threshold
        BURNING/SUSTAINED → QUENCH          : beta > disruption_limit
        Any             → SHUTDOWN          : abort_trigger
        QUENCH          → COLD              : quench 타이머 완료
    """

    def __init__(self, config: PlasmaFSMConfig) -> None:
        self.config = config
        self._phase: PlasmaPhase = PlasmaPhase.COLD
        self._preheating_start: float = 0.0
        self._ignition_start: float = 0.0
        self._quench_start: float = 0.0

    @property
    def phase(self) -> PlasmaPhase:
        return self._phase

    def update(self, ctx: PlasmaFSMContext) -> PlasmaPhase:
        """
        현재 상태와 관측 컨텍스트를 바탕으로 다음 상태를 결정하고 반환.
        """
        cfg = self.config
        t = ctx.t_s

        # 최우선: abort → SHUTDOWN (SHUTDOWN 상태는 유지)
        if ctx.abort_trigger and self._phase != PlasmaPhase.SHUTDOWN:
            self._phase = PlasmaPhase.SHUTDOWN
            return self._phase

        if self._phase == PlasmaPhase.SHUTDOWN:
            return self._phase

        # COLD → PREHEATING
        if self._phase == PlasmaPhase.COLD:
            if ctx.go_command and ctx.heating_available:
                self._phase = PlasmaPhase.PREHEATING
                self._preheating_start = t
            return self._phase

        # PREHEATING → IGNITION_ATTEMPT
        if self._phase == PlasmaPhase.PREHEATING:
            elapsed = t - self._preheating_start
            if elapsed >= cfg.preheating_duration_s and ctx.plasma_temp_kev >= cfg.ignition_temp_kev:
                self._phase = PlasmaPhase.IGNITION_ATTEMPT
                self._ignition_start = t
            return self._phase

        # IGNITION_ATTEMPT → BURNING / QUENCH
        if self._phase == PlasmaPhase.IGNITION_ATTEMPT:
            elapsed = t - self._ignition_start
            if ctx.lawson_satisfied:
                self._phase = PlasmaPhase.BURNING
            elif elapsed >= cfg.ignition_attempt_timeout_s:
                self._phase = PlasmaPhase.QUENCH
                self._quench_start = t
            return self._phase

        # BURNING → SUSTAINED / QUENCH
        if self._phase == PlasmaPhase.BURNING:
            if ctx.beta > cfg.disruption_beta_limit:
                self._phase = PlasmaPhase.QUENCH
                self._quench_start = t
            elif ctx.q_factor > cfg.sustained_q_threshold:
                self._phase = PlasmaPhase.SUSTAINED
            return self._phase

        # SUSTAINED → QUENCH
        if self._phase == PlasmaPhase.SUSTAINED:
            if ctx.beta > cfg.disruption_beta_limit:
                self._phase = PlasmaPhase.QUENCH
                self._quench_start = t
            return self._phase

        # QUENCH → COLD
        if self._phase == PlasmaPhase.QUENCH:
            elapsed = t - self._quench_start
            if elapsed >= cfg.quench_duration_s:
                self._phase = PlasmaPhase.COLD
            return self._phase

        return self._phase
