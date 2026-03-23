# FusionCore v0.1.0 — 핵융합 우주 추진 코어

> **정체성**: D-T 핵융합 반응에서 전력(MW)과 추력(N)을 뽑아내는 **범용 플라즈마 런타임**.
> 기본 검증 경로: **D-T 반응** (토카막 기반 전력 생산 → 전기추진 구동).
> 직접 추진(DFD) 모드도 지원하나, 현 버전의 핵심은 **발전 → 전기추진 변환** 경로.
> 출력 인터페이스: `power_total_mw`, `thrust_n`, `isp_s`, `omega_fusion`, `chain` — 어떤 우주선에든 pluggable.

---

## 한눈에 보기

| 항목 | 내용 |
|------|------|
| 언어 | Python 3.9+ (stdlib only) |
| 버전 | v0.1.0 |
| 테스트 | 127 passed (§1~§15) |
| 핵심 반응 | **D-T** (기본 검증 경로) / D-He3·D-D·p-B11 (확장 인터페이스) |
| 출력 | 전력 [MW], 추력 [N], Isp [s] |
| 감사 | SHA-256 FusionChain |
| 독립성 | YES — 단독 사용 가능 |
| 통합 | StarCraft OS submodule |

---

## 핵심 개념

### FusionCore ≠ TerraCore

| 구분 | FusionCore | TerraCore |
|------|-----------|-----------|
| 반응 유형 | 공학적 제어 핵융합 (토카막) | 자연 항성 핵합성 (중력 가둠) |
| 온도 범위 | 10~200 keV | 수백만~수억 K |
| 출력 형태 | 전력 + 추력 | 원소 합성 + 대기/생태계 |
| 목적 | 우주선 동력 | 우주선 생명유지 |
| 독립 사용 | YES | YES |

---

## 핵심 물리 수식

### 1. D-T 핵융합 반응률 `<σv>(T)`

```
반응:  ²H + ³H → ⁴He (3.52 MeV) + n (14.06 MeV)
총 에너지: E_DT = 17.58 MeV = 2.818 × 10⁻¹² J

반응률:
  <σv>(T) = 조각선형 보간  [NRL 데이터]
  T [keV]:    1      2      5     10     20     50    100    200
  <σv>[m³/s]: 6.6e-27 4.6e-25 1.3e-23 1.1e-22 4.3e-22 8.3e-22 8.1e-22 6.3e-22

출력 전력:
  P_fusion = n_D × n_T × <σv>(T) × E_DT × V_plasma   [W]
```

### 2. 플라즈마 열 방정식 (0D 근사 + Euler 적분)

```
dT_plasma/dt = (P_heating - P_loss) / (n × k_B × V)

⚠️ 0D (점 모델) 근사: 공간 분포 무시, 단일 온도 대표값 사용
   - 실제 토카막: 반경 방향 온도 프로파일 존재 (T_core ≫ T_edge)
   - 현 모델은 개략적 에너지 수지 추정 용도

P_heating : 외부 가열 전력
P_loss    : 복사 + 전도 손실 (근사)
n         : 플라즈마 밀도
k_B       : 볼츠만 상수
V         : 플라즈마 체적
```

### 3. Lawson 기준 (점화 임계)

```
삼중곱:  n × τ_E × T ≥ 3 × 10²¹  [m⁻³·s·keV]

Q 인자:  Q = P_fusion / P_heating
         Q > 1  : 에너지 이득
         Q ≥ 5  : 실용 핵융합
         Q → ∞  : 이상적 자가 유지 (현 0D 모델에서는 고Q 수렴으로 근사, 실제 점화 아님)

베타:    β = (n × k_B × T) / (B²/2μ₀)
         β < β_max  : 안정
```

### 4. 방열판 복사 (Stefan-Boltzmann)

```
P_rad = ε × σ × A × T_radiator⁴    [W]
ε   : 방사율 (0.85~0.95)
σ   : Stefan-Boltzmann 상수 = 5.67 × 10⁻⁸ W·m⁻²·K⁻⁴
A   : 방열 면적 [m²]
```

### 5. 중성자 차폐 (Beer-Lambert — 선량 추정 MVP)

```
Φ_n = P_neutron / (4π × r² × E_n)          [n/m²·s]
감쇠: I = I₀ × exp(-μ × x)
선량률: D = Φ_n × σ_bio × E_n / ρ_tissue    [Sv/hr]

⚠️ MVP 수준 추정 모델:
   - 단일 물질 균질 차폐 가정 (실제: 다층 복합재)
   - 산란 스펙트럼 무시, 단일 에너지 근사
   - 선량은 안전 한계 초과 여부 판단 지표로만 활용
```

### 6. 추진 계산 (Power-to-Thrust Abstraction)

```
⚠️ 추진 계산은 "전력 → 추력" 변환 추상화:
   핵융합로가 전기를 생산하고, 그 전기로 이온 추진기를 구동하는 경로.
   실제 핵융합-직접추진(DFD) 플라즈마 물리는 별도 모델 필요.

전기추진 모드 (Electric Ion — 기본 경로):
  v_e = Isp × g₀               [m/s],  g₀ = 9.80665
  F   = 2 × P_thrust / v_e     [N]     ← 전기 → 추력 변환
  Isp ≈ 3,000 ~ 10,000 s

직접추진 모드 (Direct Fusion Drive — 확장):
  v_e = Isp × g₀               [m/s]
  F   = ṁ × v_e                [N]
  Isp ≈ 10,000 ~ 20,000 s

질량 유량:
  ṁ = F / (Isp × g₀)           [kg/s]

Tsiolkovsky:
  Δv = Isp × g₀ × ln(m₀/m_f)  [m/s]
```

### 7. Ω_fusion 건강도

```
Ω_plasma   = f(β, Q, 플라즈마 위상)
Ω_thermal  = f(열 여유율, 방열판 온도)
Ω_shield   = f(선량률 < 한계치)
Ω_fuel     = f(연료 잔량 / 초기 연료)
Ω_power    = f(전력 배분 효율)

Ω_fusion = Ω_plasma×0.30 + Ω_thermal×0.25 + Ω_shield×0.20
          + Ω_fuel×0.15  + Ω_power×0.10

판정: OPTIMAL(≥0.80) / NOMINAL(0.60~) / DEGRADED(0.40~) / CRITICAL(<0.40)
```

---

## 플라즈마 FSM (7단계)

```
COLD
 └→ PREHEATING      (외부 가열 시작)
     └→ IGNITION_ATTEMPT  (점화 조건 탐색)
         ├→ BURNING        (반응 진행 중)
         │   └→ SUSTAINED  (자가 유지 점화)
         └→ QUENCH         (점화 실패)
             └→ SHUTDOWN   (완전 정지)
```

---

## 전력 배분 우선순위

```
1순위: Parasitic    — 자체 구동 전력 (냉각·제어·계측)
2순위: Min_Electric — 최소 전기 공급 (생명유지)
3순위: Thermal_Mgmt — 열관리 (방열판 구동)
4순위: Thrust       — 추진 (잉여 전력)
```

---

## SHA-256 감사 체인 (FusionChain)

모든 텔레메트리 프레임을 불변 체인으로 기록한다.

```python
# 체인 구조
Block {
    index:      int
    timestamp:  float
    event_type: str         # "TICK" / "IGNITION" / "ABORT" / ...
    payload:    dict        # 상태 요약
    prev_hash:  str         # 이전 블록 SHA-256
    this_hash:  str         # 현재 블록 SHA-256
}

# 무결성 검증
agent._chain.verify_integrity()  # → True / False
```

**검증 방법:**
```python
from fusion_core import FusionAgent, FusionAgentConfig

agent = FusionAgent(FusionAgentConfig())
agent.ignite()
for _ in range(20):
    agent.tick()

assert agent._chain.verify_integrity(), "체인 무결성 실패"
print(f"체인 길이: {agent._chain.length}")
print(f"최신 해시: {agent._chain.latest_hash[:16]}...")
```

---

## 구조

```
fusion_core/
├── contracts/
│   └── schemas.py        — 14개 frozen dataclass + 6개 enum
├── physics/
│   ├── reaction.py       — <σv>(T) NRL 조각선형 보간
│   ├── thermal.py        — Stefan-Boltzmann 방열판
│   ├── shielding.py      — Beer-Lambert 중성자 차폐
│   ├── propulsion.py     — F=2P/v_e 추진 모드
│   └── integrator.py     — RK4 수치 적분
├── plasma/
│   ├── confinement.py    — Lawson 기준, Q 인자, β
│   └── plasma_fsm.py     — 7단계 플라즈마 FSM
├── power/
│   └── power_bus.py      — 4단계 우선순위 전력 배분
├── safety/
│   ├── omega_monitor.py  — Ω_fusion 5레이어 건강도
│   └── abort_system.py   — 4단계 중단 우선순위
├── audit/
│   └── fusion_chain.py   — SHA-256 감사 체인
├── bridge/
│   ├── rocket_spirit.py  — Rocket_Spirit 연동
│   └── brain_core.py     — CookiieBrain 연동
└── fusion_agent.py       — 10단계 tick 파이프라인
```

---

## 빠른 시작

```python
from fusion_core import FusionAgent, FusionAgentConfig

agent = FusionAgent(FusionAgentConfig())
agent.ignite()

for _ in range(30):
    frame = agent.tick()

print(f"전력: {frame.state.reaction.power_total_mw:.1f} MW")
print(f"추력: {frame.state.propulsion.thrust_n:.0f} N")
print(f"Isp:  {frame.state.propulsion.isp_s:.0f} s")
print(f"Ω:    {frame.health.omega_fusion:.3f}")
print(f"체인: {agent._chain.verify_integrity()}")
```

---

## 확장성 (Extension Points)

| 레이어 | 현재 | 확장 방향 |
|--------|------|-----------|
| 반응 | **D-T** (기본 검증 경로) + D-He3·D-D·p-B11 인터페이스 (미검증) | 정밀 핵단면적 데이터 교체 |
| 플라즈마 | **0D** Euler 적분 (점 모델 근사) | MHD 솔버 / ITER 반경 프로파일 |
| 열 | Stefan-Boltzmann 복사 (단층 균질 가정) | 다층 방열판 / 열파이프 |
| 차폐 | Beer-Lambert **선량 추정 MVP** (단일 물질·에너지) | 몬테카를로 중성자 수송 |
| 추진 | 전기추진 (power→thrust 추상화) + DFD 확장 | VASIMR / 펄스 핵융합 |
| 안전 | Ω 5레이어 | ML 이상 탐지 |
| 감사 | SHA-256 체인 | 분산 원장 연동 |

---

## 활용성 (Use Cases)

```
단독 사용:
  - 핵융합 우주선 추진 시뮬레이션
  - D-T 반응 전력 출력 연구
  - 플라즈마 제어 알고리즘 개발
  - 우주 방사선 차폐 설계 연구

StarCraft OS 통합:
  FusionCore.power_mw  → TerraCore 전기분해 전력
  FusionCore.thrust_n  → Rocket_Spirit Δv 계산
  FusionCore.chain     → StarCraft 통합 감사 로그
```

---

## 테스트

```bash
cd FusionCore_Stack
python -m pytest tests/test_fusion_core.py -v
# 127 passed  §1~§15
```

§1 FuelState / §2 PlasmaState / §3 ReactionState / §4 ThermalState /
§5 ShieldingState / §6 PowerBusState / §7 PropulsionState / §8 FusionCoreState /
§9 플라즈마 FSM / §10 Lawson / §11 추진 / §12 Ω monitor /
§13 abort system / §14 FusionChain / §15 FusionAgent 통합

---

## 연계 레포

| 레포 | 관계 |
|------|------|
| [StarCraft](https://github.com/qquartsco-svg/StarCraft) | FusionCore를 submodule로 포함하는 통합 OS |
| [TerraCore](https://github.com/qquartsco-svg/TerraCore) | 생명유지 엔진 (H₂ → FusionCore 연료 피드백) |
| [Rocket_Spirit](https://github.com/qquartsco-svg/Rocket_Spirit) | FusionCore 추력을 Δv로 변환 |

---

> 이 소프트웨어는 **연구·교육용 시뮬레이션**입니다.
> 실제 핵융합 추진기 설계 완성본이 아닙니다 — 0D 근사 모델이며 엔지니어링 인증 불가.
> 실제 핵융합 장치 운용, 우주 추진 인증, 안전 필수 제어 시스템 용도로 사용할 수 없습니다.
