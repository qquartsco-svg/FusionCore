"""
fusion_core/audit/fusion_chain.py
핵융합 코어 감사 체인 (FusionChain) 모듈.

FlightChain 패턴을 계승하는 불변 SHA-256 블록체인 구조.
모든 원격측정 프레임과 이벤트를 순차적으로 기록하며
무결성을 해시 체인으로 보증한다.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class FusionBlock:
    """감사 체인의 단일 블록 — 불변 레코드."""

    index: int
    t_s: float
    payload_json: str
    prev_hash: str
    block_hash: str
    event_type: str   # "TELEMETRY" | "IGNITION" | "QUENCH" | "ABORT" | "STAGE_EVENT"


class FusionChain:
    """
    핵융합 코어 감사 체인.

    SHA-256 해시 체인으로 모든 원격측정·이벤트를 기록.
    FlightChain과 동일한 패턴을 따른다.
    """

    def __init__(self, reactor_id: str, record_interval: int = 10) -> None:
        self.reactor_id = reactor_id
        self.record_interval = record_interval
        self._blocks: list[FusionBlock] = []
        self._tick_counter: int = 0
        # 제네시스 블록
        genesis = FusionBlock(
            index=0,
            t_s=0.0,
            payload_json=json.dumps({"reactor_id": reactor_id, "genesis": True}),
            prev_hash="0" * 64,
            block_hash=self._compute_hash(0, 0.0, json.dumps({"reactor_id": reactor_id}), "0" * 64),
            event_type="STAGE_EVENT",
        )
        self._blocks.append(genesis)

    def _compute_hash(self, index: int, t_s: float, payload_json: str, prev_hash: str) -> str:
        """SHA-256(index|t_s|payload|prev_hash)."""
        raw = f"{index}|{t_s}|{payload_json}|{prev_hash}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _append(self, t_s: float, payload: dict, event_type: str) -> FusionBlock:
        """블록 생성 및 체인에 추가."""
        index = len(self._blocks)
        prev_hash = self._blocks[-1].block_hash
        payload_json = json.dumps(payload, default=str)
        block_hash = self._compute_hash(index, t_s, payload_json, prev_hash)
        block = FusionBlock(
            index=index,
            t_s=t_s,
            payload_json=payload_json,
            prev_hash=prev_hash,
            block_hash=block_hash,
            event_type=event_type,
        )
        self._blocks.append(block)
        return block

    def record(self, frame) -> None:
        """
        주기적 원격측정 기록 (record_interval 틱마다).

        frame: TelemetryFrame (순환 참조 방지를 위해 타입 힌트 생략)
        """
        self._tick_counter += 1
        if self._tick_counter % self.record_interval == 0:
            self._append(
                t_s=frame.t_s,
                payload=frame.summary_dict(),
                event_type="TELEMETRY",
            )

    def record_event(self, t_s: float, event_type: str, data: dict) -> None:
        """
        즉각 이벤트 기록 (점화·quench·abort 등).

        항상 기록한다 (interval 무관).
        """
        payload = {"event": event_type, "t_s": t_s, **data}
        self._append(t_s=t_s, payload=payload, event_type=event_type)

    def verify_integrity(self) -> bool:
        """전체 체인 해시 검증."""
        if len(self._blocks) < 2:
            return True
        for i in range(1, len(self._blocks)):
            blk = self._blocks[i]
            prev = self._blocks[i - 1]
            # prev_hash 일치 확인
            if blk.prev_hash != prev.block_hash:
                return False
            # block_hash 재계산 일치 확인
            expected = self._compute_hash(blk.index, blk.t_s, blk.payload_json, blk.prev_hash)
            if blk.block_hash != expected:
                return False
        return True

    def export_json(self, path: str) -> None:
        """체인 전체를 JSON 파일로 내보내기."""
        data = [
            {
                "index": b.index,
                "t_s": b.t_s,
                "event_type": b.event_type,
                "prev_hash": b.prev_hash,
                "block_hash": b.block_hash,
                "payload": json.loads(b.payload_json),
            }
            for b in self._blocks
        ]
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"reactor_id": self.reactor_id, "chain": data}, f, indent=2)

    @property
    def blocks(self) -> list[FusionBlock]:
        """블록 목록 읽기 전용 뷰."""
        return list(self._blocks)

    def __len__(self) -> int:
        return len(self._blocks)
