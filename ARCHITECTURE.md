# FusionCore_Stack — 아키텍처 및 작동 원리

> v0.1.0 · 127/127 PASS · stdlib only

---

## 이 문서가 무엇인가

FusionCore_Stack이 어떻게 설계되어 있고, 매 틱(tick)마다 무슨 일이 일어나며,
각 레이어가 왜 그 위치에 있는지를 실제 구현된 코드 기준으로 설명한다.

---

## 1. 설계 철학

### "상태는 추정이다"

FusionCore의 모든 상태 객체(`PlasmaState`, `ThermalState` 등)는
`@dataclass(frozen=True)` — 불변이다.

한 번 만들어진 상태는 수정되지 않는다.
다음 상태는 항상 새로운 객체로 생성된다.

```python
# 이렇게 하지 않는다 (금지)
state.temperature_kev = 15.0

# 이렇게 한다 (새 객체)
new_plasma = PlasmaState(
    temperature_kev=15.0,
    density_m3=state.density_m3,
    ...
)
```

이 패턴이 보장하는 것:
- 어느 시각의 상태든 독립적으로 비교·저장·검증 가능
- 버그가 생겨도 "언제 어디서" 상태가 바뀌었는지 역추적 가능
- FusionChain(감사 체인)과 자연스럽게 연결됨

### "하드코딩은 없다"

중력 상수 `g₀`, 스테판-볼츠만 상수 `σ`, 볼츠만 상수 `k_B` —
모두 `FusionPhysicsConfig` 객체에 있다.

```python
config = FusionPhysicsConfig(
    g0=9.80665,          # 지구 기준
    # g0=1.62,           # 달 환경으로 교체하면 전체가 달 기준으로 동작
)
```

반응 파라미터도 마찬가지다:
```python
reaction_config = ReactionConfig(
    reaction_type=ReactionType.DT,         # D-T 반응
    chamber_volume_m3=100.0,               # 챔버 크기
    min_ignition_temp_kev=4.0,             # 점화 온도 임계
)
```

### "연결은 선택적이다"

Rocket_Spirit, CookiieBrain이 없어도 FusionCore는 완전히 작동한다.

```python
# bridge/rocket_spirit.py
try:
    from launch_vehicle.contracts.schemas import TelemetryFrame as RSFrame
    ROCKET_SPIRIT_AVAILABLE = True
except ImportError:
    ROCKET_SPIRIT_AVAILABLE = False
```

---

## 2. 전체 구조

```
FusionCore_Stack/
├── fusion_core/
│   ├── contracts/
│   │   └── schemas.py          Layer 0 — 데이터 계약 (14개 상태 객체)
│   ├── physics/
│   │   ├── reaction.py         Layer 1a — 핵융합 반응률·출력
│   │   ├── thermal.py          Layer 1b — 열·방열판 동역학
│   │   ├── shielding.py        Layer 1c — 중성자 차폐
│   │   ├── propulsion.py       Layer 1d — 추력 계산
│   │   └── integrator.py       Layer 1e — RK4 적분기
│   ├── plasma/
│   │   ├── confinement.py      Layer 2a — 플라즈마 가둠 평가
│   │   └── plasma_fsm.py       Layer 2b — 플라즈마 위상 FSM
│   ├── power/
│   │   └── power_bus.py        Layer 3 — 전력 배분
│   ├── safety/
│   │   ├── omega_monitor.py    Layer 4a — Ω 건전성 관측
│   │   └── abort_system.py     Layer 4b — 중단 결정
│   ├── audit/
│   │   └── fusion_chain.py     Layer 4c — SHA-256 감사 체인
│   ├── bridge/
│   │   ├── rocket_spirit.py    브릿지 — Rocket_Spirit 연동
│   │   └── brain_core.py       브릿지 — CookiieBrain 연동
│   └── fusion_agent.py         오케스트레이터 — 10단계 파이프라인
└── tests/
    └── test_fusion_core.py     127 케이스
```

---

## 3. Layer 0 — 데이터 계약 (`contracts/schemas.py`)

**모든 데이터 구조가 여기서 정의된다.**
나머지 레이어는 이 계약을 읽기만 하고 수정하지 않는다.

### 핵심 객체 14개

| 객체 | 설명 | 단위 |
|------|------|------|
| `FusionPhysicsConfig` | 물리 상수 (frozen 아님 — 주입 가능) | SI |
| `FuelState` | 연료 잔량 + 소모율 | kg |
| `PlasmaState` | 온도·밀도·가둠시간·Q인자·베타 | keV, m⁻³, s |
| `ReactionState` | 총출력·하전입자·중성자 출력·반응률 | MW, m³/s |
| `ThermalState` | 코어·방열판 온도·열마진 | K, MW |
| `ShieldingState` | 중성자 플럭스·선량률·차폐 질량 | m⁻²s⁻¹, Sv/hr, kg |
| `PowerBusState` | 전기·추진·열관리 배분 | MW |
| `FusionPropulsionState` | 추력·Isp·배기 속도 | N, s, m/s |
| `FusionCoreState` | 위 7개를 묶은 전체 스냅샷 | — |
| `FusionHealth` | Ω 5개 + 판정 + 경보 | [0,1] |
| `TelemetryFrame` | 단일 시각의 전체 기록 | — |

### 열거형 6개

| 열거형 | 값 |
|--------|-----|
| `ReactionType` | DT / DHE3 / DD / PB11 |
| `PlasmaPhase` | COLD / PREHEATING / IGNITION_ATTEMPT / BURNING / SUSTAINED / QUENCH / SHUTDOWN |
| `PropulsionMode` | OFF / ELECTRIC_ONLY / DIRECT_THRUST / HYBRID |
| `AbortMode` | NONE / CONTROLLED_SHUTDOWN / EMERGENCY_QUENCH / MAGNETIC_DUMP |

---

## 4. Layer 1 — 물리 엔진 (`physics/`)

### 4-1. 핵융합 반응 (`reaction.py`)

**핵심 질문: 주어진 플라즈마 조건에서 얼마만큼의 에너지가 나오는가?**

#### 반응별 에너지 분율

| 반응 | 하전입자 | 중성자 | 하전 분율 |
|------|---------|--------|----------|
| D-T | 3.5 MeV (α) | 14.1 MeV | **19.9%** |
| D-He3 | 18.3 MeV | ≈0 | **94%** |
| D-D | ≈2.45 MeV | ≈2.45 MeV | **67%** |
| p-B11 | 8.7 MeV (3α) | 0 | **99%** |

하전 분율이 높을수록:
- 직접 추진으로 연결 가능한 에너지가 많다
- 중성자 차폐 부담이 줄어든다
- 단, 점화 온도가 훨씬 높아진다 (D-T: ~4 keV, p-B11: ~200 keV)

#### 반응률 `<σv>` 계산

온도에 따른 반응 확률 `<σv>` [m³/s]를 **NRL Plasma Formulary** 데이터 기반
조각선형 보간으로 계산한다.

```
D-T <σv> [m³/s]:

  10⁻²² ┤                 ●───●
         │            ●
  10⁻²³ ┤         ●
         │
  10⁻²⁴ ┤      ●
         │
  10⁻²⁵ ┤   ●
         └──────────────────────
           1    5   10  20  50 100  200  [keV]
```

```python
def _reactivity_dt(self, T_kev: float) -> float:
    T_data  = [1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0]
    sv_data = [6.60e-27, 4.56e-25, 1.27e-23, 1.12e-22,
               4.33e-22, 8.29e-22, 8.12e-22, 6.29e-22]
    return max(0.0, _lerp(T_kev, T_data, sv_data))
```

D-He3는 같은 온도에서 D-T보다 반응률이 **약 500배** 낮다.
이것이 D-He3가 이상형이지만 현실적으로 어려운 이유다.

#### 출력 계산

```
반응 출력 밀도 [W/m³] = n_D × n_T × <σv> × E_fusion_J
총 출력 [MW]          = 출력 밀도 × 챔버 체적
하전입자 출력 [MW]    = 총 출력 × charged_fraction
중성자 출력 [MW]      = 총 출력 × (1 - charged_fraction)
연료 소모율 [kg/s]    = (총 출력 [W] / Q_fusion [J]) × pair_mass [kg]
```

#### 점화 조건

```python
if T_kev < self.config.min_ignition_temp_kev:
    # 점화 온도 미달 → 출력 0, 연료 소모 없음
    power_total_mw = 0.0
```

---

### 4-2. 열 관리 (`thermal.py`)

**핵심 질문: 반응로가 발생시키는 열을 우주에서 어떻게 버리는가?**

우주에는 공기가 없다. 유일한 냉각 수단은 **복사(Radiation)** 뿐이다.

#### 방열판 복사 출력

```
P_rad [MW] = ε × σ_SB × A_rad × T_rad⁴
```

- `ε = 0.9` (방사율)
- `σ_SB = 5.670×10⁻⁸ W/(m²·K⁴)`
- `A_rad = 5000 m²` (기본값)
- `T_rad` [K]: 방열판 온도

T⁴ 의존성: 온도를 2배로 올리면 방열 능력이 **16배** 증가한다.

#### 방열판 온도 동역학

```
dT_rad/dt = (Q_in - P_rad) / C_thermal

Q_in     = 중성자 출력 + 총 출력의 5% (기생 열)
P_rad    = ε·σ·A·T_rad⁴
C_thermal = 1×10⁸ J/K (냉각계 열용량)
```

방열판이 충분히 넓지 않으면 온도가 계속 상승하다가 `thermal_margin → 0` 이 된다.

#### 열 마진

```
thermal_margin = (T_max - T_core) / T_max ∈ [-1, 1]
```

`thermal_margin < 0.05` → AbortSystem이 중단 명령을 내린다.

---

### 4-3. 중성자 차폐 (`shielding.py`)

**핵심 질문: 14.1 MeV 중성자로부터 승무원을 보호하는 데 얼마나 무거운 차폐재가 필요한가?**

D-T 반응의 에너지 중 **80.1%가 14.1 MeV 중성자**로 나온다.
이 중성자는 차폐하지 않으면 인체에 치명적이고 구조재를 손상시킨다.

#### 중성자 플럭스

```
Φ [m⁻²s⁻¹] = P_neutron [W] / (4π × r² × E_n [J])

r    = 승무원까지 거리 (기본 20 m)
E_n  = D-T 기준 14.1 MeV = 2.259×10⁻¹² J
```

#### Beer-Lambert 차폐 두께

```
x [m] = ln(Φ / Φ_limit) / μ

μ    = 납 14MeV 중성자 감쇠계수 ≈ 0.083 m⁻¹
Φ_limit = 최대 허용 선량률로부터 역산한 허용 플럭스
```

#### 차폐 질량

```
m_shield [kg] = ρ_납 × A_차폐 × x
              = 11340 × 50 × x
```

D-He3, p-B11는 중성자 출력이 거의 없으므로 차폐 질량이 대폭 줄어든다.
이것이 장기 우주 임무에서 저중성자 반응이 매력적인 이유다.

---

### 4-4. 핵융합 추진 (`propulsion.py`)

**핵심 질문: 핵융합 에너지를 어떻게 추력으로 변환하는가?**

세 가지 모드가 있다.

#### 모드 1: ELECTRIC_ONLY (전기추진)

```
v_e      = Isp × g₀  (기본 Isp = 5000 s → v_e = 49,033 m/s)
P_eff    = P_thrust [W] × 0.65 (전기추진 효율)
F        = 2 × P_eff / v_e
ṁ_prop   = F / v_e
```

핵융합 전력으로 홀 추진기(Hall thruster)를 구동하는 방식.
Isp가 높아 연료 효율이 좋지만, 추력이 작다.

#### 모드 2: DIRECT_THRUST (직접 추진)

```
v_e      = Isp_자기노즐 × g₀  (추정 Isp = 20,000 s → v_e = 196,133 m/s)
P_eff    = P_charged [W] × 0.60 (자기노즐 효율)
F        = 2 × P_eff / v_e
```

핵융합 하전입자를 자기노즐로 직접 배기하는 방식.
Isp가 훨씬 높다 (20,000 s vs 5,000 s).
NASA NIAC 연구의 Direct Fusion Drive 개념에 해당.

#### 모드 3: HYBRID

```
전력을 반반 분배:
  전기추진 절반 + 직접추진 절반
유효 Isp = F_total / (ṁ_total × g₀)
```

---

### 4-5. 적분기 (`integrator.py`)

**RK4 (4차 룽게-쿠타)로 연속 동역학을 이산 시간으로 수치 적분한다.**

#### 연료 질량 적분

```
dm/dt = -ṁ_fuel

k1 = f(m)
k2 = f(m + dt/2 × k1)
k3 = f(m + dt/2 × k2)
k4 = f(m + dt × k3)
m_new = m + dt/6 × (k1 + 2k2 + 2k3 + k4)
```

#### 플라즈마 온도 적분

```
dT/dt = (P_heat + P_alpha - P_loss) / C_plasma [keV/s]

P_heat  = 외부 가열 전력 [MW]
P_alpha = 핵융합 알파 입자 자가 가열 (charged 출력의 20%)
P_loss  = T × 5.0 (단순 선형 손실 모델)
C_plasma = 50 MW/keV (열용량 추정)
```

#### 방열판 온도 적분

```
dT_rad/dt = (Q_in - P_rad) / C_thermal [K/s]
```

---

## 5. Layer 2 — 플라즈마 제어 (`plasma/`)

### 5-1. 가둠 평가 (`confinement.py`)

**핵심 질문: 플라즈마가 자립 연소 조건을 만족하는가?**

#### 로손(Lawson) 기준

핵융합이 자립 연소하기 위한 최소 조건:

```
n × τ × T > 임계값

n   = 입자 수밀도 [m⁻³]
τ   = 에너지 가둠 시간 [s]
T   = 온도 [keV]

D-T 임계값:  3×10²¹ keV·s/m³ (Q=1 기준)
D-He3 임계: 1×10²³ keV·s/m³ (D-He3는 10배 어렵다)
```

현재 코드의 기본값 (`n=10²⁰ m⁻³, τ=3 s, T=10 keV`):
```
triple_product = 10²⁰ × 3 × 10 = 3×10²¹ → D-T 로손 기준 경계
```

#### Q 인자 추정

```
Q = P_fusion / P_heating

Q < 1 : 에너지 소비 (가열 전력 > 핵융합 출력)
Q = 1 : 손익분기
Q = 10: ITER 목표
Q > 1 : BURNING 상태로 전이 가능
```

#### 베타 (β) 추정

```
β = n·k_B·T / (B²/2μ₀)
  ≈ n · T_kev · kev_to_j / (B² / 2μ₀)

B = 5 T (기본 자기장)
```

β가 너무 높으면 (> 0.08) 플라즈마가 불안정해져 붕괴(disruption)한다.

---

### 5-2. 플라즈마 FSM (`plasma_fsm.py`)

**핵심 질문: 플라즈마가 지금 어느 단계에 있고, 다음 단계로 갈 수 있는가?**

#### 7단계 상태 전이도

```
                     go_command
                     & heating_available
         ┌──────────────────────────────────────┐
         ↓                                      │
       COLD ──────────────────────────── SHUTDOWN ←── abort_trigger (어느 상태에서든)
         │                                      ↑
         │  예열 타이머(30s) 완료                │
         │  & T > 4 keV                         │
         ↓                                      │
    PREHEATING                                  │
         │                                      │
         │  로손 조건 충족 가능성 진입           │
         ↓                                      │
  IGNITION_ATTEMPT ──────────────────────────────┘
         │                 ↑ 타임아웃(60s) & 로손 미충족 → QUENCH
         │  lawson_satisfied                     │
         ↓                                      │
      BURNING ──── beta > 0.08 ────────────────→ QUENCH
         │                                        ↑
         │  Q > 1.0                               │
         ↓                                      │
     SUSTAINED ─── beta > 0.08 ──────────────────┘
                                      quench 타이머(5s)
                                      완료 후 → COLD
```

#### 핵심 전이 조건

| 전이 | 조건 |
|------|------|
| COLD → PREHEATING | `go_command AND heating_available` |
| PREHEATING → IGNITION_ATTEMPT | `경과시간 ≥ 30s AND T > 4 keV` |
| IGNITION_ATTEMPT → BURNING | `lawson_satisfied == True` |
| IGNITION_ATTEMPT → QUENCH | `경과시간 ≥ 60s AND NOT lawson` |
| BURNING → SUSTAINED | `Q > 1.0` |
| BURNING/SUSTAINED → QUENCH | `β > 0.08` |
| Any → SHUTDOWN | `abort_trigger == True` |
| QUENCH → COLD | `quench 경과시간 ≥ 5s` |

---

## 6. Layer 3 — 전력 버스 (`power/power_bus.py`)

**핵심 질문: 핵융합에서 나온 하전입자 전력을 어디에 얼마나 배분할 것인가?**

하전입자 출력만 전기·추진으로 변환 가능하다.
중성자 출력은 열 부하와 차폐 부담이 된다.

#### 배분 우선순위

```
총 가용 전력 = reaction.power_charged_mw

1. 기생 손실 차감 (3%)
   P_parasite = 총 × 0.03

2. 최소 전기 보장 (생명유지·항법)
   P_electric_min = max(10 MW, 요청량)

3. 열관리 배분 (5%)
   P_thermal_mgmt = 총 × 0.05

4. 나머지 → 추진 배분 (mode에 따라)
```

#### 모드별 배분

| 모드 | 전기 배분 | 추진 배분 |
|------|----------|----------|
| OFF | 최소 전기만 | 0 |
| ELECTRIC_ONLY | 기본 수요 | 잔여 전부 |
| DIRECT_THRUST | 최소 전기 | 잔여 전부 |
| HYBRID | 기본 수요 | 잔여 전부 (engine 내부에서 반반) |

---

## 7. Layer 4 — 안전·감사

### 7-1. Ω 건전성 관측기 (`safety/omega_monitor.py`)

**핵심 질문: 지금 이 시스템이 얼마나 건강한가?**

#### Ω_fusion 계산

```
Ω_fusion = 0.30 × Ω_plasma
         + 0.25 × Ω_thermal
         + 0.20 × Ω_shielding
         + 0.15 × Ω_fuel
         + 0.10 × Ω_power
```

각 부분 지수:

**Ω_plasma** (가중합):
```
Q 점수      = min(1.0, Q / 5.0)               × 0.40
베타 여유   = (0.10 - β) / 0.10              × 0.30
온도 점수   = min(1.0, T_kev / 20.0)         × 0.15
위상 점수   = {COLD:0.1, PREHEATING:0.3,     × 0.15
               IGNITION:0.5, BURNING:0.8,
               SUSTAINED:1.0, QUENCH:0.0}
```

**Ω_thermal**: `= thermal_margin` (직접 사용)

**Ω_shielding**: `= margin_fraction` (직접 사용)

**Ω_fuel**: `= remaining_fraction()` (잔여 연료 분율)

**Ω_power**: `= min(1.0, electric_mw / base_demand_mw)`

#### 판정

| Ω_fusion | 판정 |
|----------|------|
| > 0.8 | **HEALTHY** |
| > 0.6 | **STABLE** |
| > 0.4 | **FRAGILE** |
| ≤ 0.4 | **CRITICAL** |

#### abort_required 조건 (OR 조합)

```python
abort_required = (
    omega_fusion < 0.25          # 종합 건전성 임계 이하
    OR beta > 0.10               # 플라즈마 붕괴 임박
    OR dose_rate > 0.1 Sv/hr     # 방사선 한계 초과
    OR thermal_margin < 0.05     # 열 한계 임박
)
```

---

### 7-2. 중단 시스템 (`safety/abort_system.py`)

**핵심 질문: 어떤 방식으로 시스템을 멈출 것인가?**

#### 4단계 우선순위 평가

```
우선순위 1 (최고): external_abort → EMERGENCY_QUENCH
우선순위 2: beta > 0.10 → MAGNETIC_DUMP  (자기 에너지 덤프)
우선순위 3: dose_rate > 한계 → CONTROLLED_SHUTDOWN
우선순위 4: thermal_margin < 0.05 → CONTROLLED_SHUTDOWN
우선순위 5: omega < 0.25 → CONTROLLED_SHUTDOWN
기본: NONE
```

#### 중단 모드별 의미

| 모드 | 상황 | 동작 |
|------|------|------|
| CONTROLLED_SHUTDOWN | 여유 있는 위험 | 플라즈마 점진적 냉각, 연료 주입 차단 |
| EMERGENCY_QUENCH | 즉각 위험 | 가열 전원 차단, 급냉 |
| MAGNETIC_DUMP | 플라즈마 붕괴 임박 | 자기장 에너지 빠르게 소산 |

---

### 7-3. 감사 체인 (`audit/fusion_chain.py`)

**핵심 질문: 사고 후 "언제, 무엇이, 왜" 일어났는지 증명할 수 있는가?**

#### SHA-256 연결 블록 구조

```
Block 0 (Genesis):
  hash = SHA-256("GENESIS|FusionCore|{reactor_id}")

Block N:
  hash = SHA-256(
      str(N) | str(t_s) | payload_json | prev_hash
  )
  prev_hash = Block N-1의 hash
```

하나의 블록이 변조되면 이후 모든 블록의 해시가 달라진다.
`verify_integrity()`로 전체 체인을 검증한다.

#### 기록 시점

| 유형 | 조건 | 이벤트 타입 |
|------|------|-------------|
| 주기 기록 | 매 10 tick (기본값) | `TELEMETRY` |
| 즉시 기록 | BURNING 진입 | `IGNITION` |
| 즉시 기록 | QUENCH 진입 | `QUENCH` |
| 즉시 기록 | SHUTDOWN 진입 | `ABORT` |
| 즉시 기록 | 기타 위상 전이 | `STAGE_EVENT` |

---

## 8. 오케스트레이터 — `fusion_agent.py`

**FusionAgent가 모든 레이어를 연결하는 중심이다.**

### 구성요소 초기화

```python
agent = FusionAgent(FusionAgentConfig(
    reactor_id="FC-001",
    dt_s=1.0,
    reaction_config=ReactionConfig(reaction_type=ReactionType.DT),
    thermal_config=ThermalConfig(radiator_area_m2=5000.0),
    ...
))
```

`FusionAgentConfig` 하나가 전체 시스템을 설정한다.
각 서브시스템은 생성 시점에 자신의 Config만 받는다.

### 제어 인터페이스

```python
agent.ignite()                         # go_command = True → PREHEATING 진입
agent.shutdown()                       # abort_trigger = True → SHUTDOWN
agent.set_mode(PropulsionMode.DIRECT_THRUST)
agent.set_throttle(0.8)               # [0, 1]
```

### tick() — 10단계 파이프라인

```
매 dt_s(기본 1.0s)마다 실행:

┌──────────────────────────────────────────────────────────┐
│  입력: 이전 시각의 상태들 (_plasma, _fuel, _thermal, ...)  │
└──────────┬───────────────────────────────────────────────┘
           │
  Step 1   │  PlasmaFSM.update(ctx)
           │  현재 관측값(T, Q, β, lawson) → 플라즈마 위상 결정
           │
  Step 2   │  FusionReactor.tick(plasma, fuel, throttle)
           │  <σv>(T) × n_D × n_T × V → 반응 출력, 연료 소모
           │
  Step 3   │  FusionIntegrator.step_plasma_temp(T, P_heat, P_alpha, P_loss)
           │  RK4: 플라즈마 온도 갱신
           │
  Step 4   │  ConfinementModel.assess(plasma)
           │  triple_product, Q인자, β 재계산
           │
  Step 5   │  ThermalSystem.tick(neutron_power + 기생열)
           │  오일러: 방열판 온도 갱신, thermal_margin 계산
           │
  Step 6   │  ShieldingModel.tick(reaction)
           │  중성자 플럭스 → 선량률 → 차폐 질량 계산
           │
  Step 7   │  PowerBusController.allocate(reaction, mode)
           │  하전입자 전력 → 전기/추진/열관리 배분
           │
  Step 8   │  FusionPropulsionEngine.tick(power_bus)
           │  배분된 추진 전력 → 추력, Isp 계산
           │
  Step 9   │  OmegaMonitor.observe(core_state)
           │  5개 부분 Ω → Ω_fusion → 판정
           │
  Step 10  │  AbortSystem.evaluate(health, state, phase)
           │  우선순위 중단 결정
           │  FusionChain.record(frame)
           │
┌──────────▼───────────────────────────────────────────────┐
│  출력: TelemetryFrame (상태 + 건전성 + 위상 + 중단모드)   │
└──────────────────────────────────────────────────────────┘
```

### 시뮬레이션 실행

```python
# 기본 시나리오
agent = FusionAgent()
agent.ignite()
agent.set_mode(PropulsionMode.ELECTRIC_ONLY)
agent.set_throttle(0.8)

frames = agent.simulate(duration_s=300.0)   # 300 tick (5분)

for f in frames:
    d = f.summary_dict()
    print(f"t={d['t_s']:.0f}s  phase={d['phase']}  "
          f"Q={d['q_factor']:.2f}  Ω={d['omega_fusion']:.3f}  "
          f"F={d['thrust_n']:.0f}N")
```

---

## 9. 브릿지 (`bridge/`)

### Rocket_Spirit 연동

```python
from fusion_core.bridge.rocket_spirit import (
    ROCKET_SPIRIT_AVAILABLE,
    bridge_fusion_to_rocket,
    bridge_rocket_to_fusion,
)

# FusionCore 추진 출력 → Rocket_Spirit PropulsionState 호환 dict
rs_input = bridge_fusion_to_rocket(fusion_state)
# {thrust_n: ..., isp_s: ..., mass_flow_kgs: ..., is_ignited: True}

# Rocket_Spirit 텔레메트리 → FusionCore 환경 파라미터
env = bridge_rocket_to_fusion(rs_telemetry)
# {altitude_m: ..., speed_ms: ..., dynamic_q_pa: ...}
```

Rocket_Spirit이 없어도 `ROCKET_SPIRIT_AVAILABLE = False`로 안전하게 동작.

### CookiieBrain 연동

```python
from fusion_core.bridge.brain_core import (
    BRAIN_AVAILABLE,
    fusion_state_to_memory,
    brain_command_to_fusion,
)

# FusionCore 상태 → BrainCore 메모리 주입
memory_dict = fusion_state_to_memory(fusion_state, health)
# {omega_fusion, plasma_phase, q_factor, thermal_margin, ...}

# BrainCore 명령 → 추진 모드·스로틀·점화 명령
mode, throttle, go = brain_command_to_fusion(brain_cmd)
```

---

## 10. 임무 흐름 — 전체 연결

```
지상 발사
   │
Rocket_Spirit ─── 대기권 상승 (0~86 km)
   │  Air_Jordan   대기 공력 모델 병행
   │
궤도 진입 (MECO)
   │
Lucifer_Engine ─── 궤도 요소 전파
   │
심우주 천이
   │
FusionCore_Stack ─── 핵융합 추진 (여기서부터)
   │
   ├── PlasmaFSM: COLD → PREHEATING → BURNING → SUSTAINED
   │
   ├── 추진 모드 선택:
   │     ELECTRIC_ONLY  → 연료 효율 최대 (Isp 5000s)
   │     DIRECT_THRUST  → 추력 최대 (Isp 20000s)
   │     HYBRID         → 균형
   │
   ├── Ω_fusion 상시 관측
   │     > 0.8 → HEALTHY, 정상 운용
   │     < 0.4 → CRITICAL, 모드 변경 검토
   │     < 0.25 → abort_required
   │
   └── FusionChain: 모든 순간 SHA-256 서명

위 전체를 CookiieBrain이 관리:
   brain_command_to_fusion() → 임무 AI가 모드·스로틀 결정
   fusion_state_to_memory()  → 현재 상태를 AI 기억에 주입
```

---

## 11. 테스트 커버리지 (127/127 PASS)

| 섹션 | 내용 | 케이스 |
|------|------|--------|
| §1 | FusionPhysicsConfig | 5 |
| §2 | FuelState | 8 |
| §3 | ReactionState 계약 | 6 |
| §4 | D-T 반응률 물리 | 10 |
| §5 | D-He3 반응률 물리 | 6 |
| §6 | ThermalSystem | 10 |
| §7 | ShieldingModel | 8 |
| §8 | ConfinementModel | 8 |
| §9 | PlasmaFSM | 12 |
| §10 | PowerBusController | 8 |
| §11 | FusionPropulsionEngine | 8 |
| §12 | OmegaMonitor | 10 |
| §13 | AbortSystem | 8 |
| §14 | FusionChain | 8 |
| §15 | FusionAgent 통합 | 12 |
| **합계** | | **127** |

---

## 12. 확장 경로

### Layer별 다음 구현 지점

| 레이어 | 현재 | 다음 |
|--------|------|------|
| 반응 물리 | NRL 조각선형 <σv> | Bosch-Hale 전체 파라미터 피트 |
| 온도 동역학 | 단순 손실 모델 (T×5) | Bremsstrahlung + 사이클로트론 복사 |
| 플라즈마 밀도 | throttle 프록시 | 입자 수지(particle balance) 방정식 |
| 자기장 | 정적 B=5T | 코일 전류·자기압력 동역학 |
| 방열판 | 단일 온도 모델 | 냉각재 루프 다단 모델 |
| 차폐 | 납 단일 재료 | 다층 차폐 (폴리에틸렌+납+B₄C) |
| 추진 | Isp 고정값 | 입자 가속 전압 의존 Isp |
| FSM | 7상태 | 재시동 이력·열화 상태 추가 |
| 전력 버스 | 정적 배분 | 실시간 부하 응답 |

### 연동 확장

```python
# v0.2.0: Lucifer_Engine 궤도 연동
from lucifer_engine import OrbitalPropagator
orbital = OrbitalPropagator.from_fusion_thrust(frame.state.propulsion)

# v0.3.0: 몬테카를로 분산 분석
from fusion_core import MonteCarloBatch
batch = MonteCarloBatch(config, n_runs=1000)
results = batch.run(thrust_sigma=0.05, temp_sigma_kev=0.5)

# v0.4.0: 멀티 반응로 배열
from fusion_core import ReactorArray
array = ReactorArray(n_reactors=3, config=config)
```

---

## 빠른 시작

```python
from fusion_core.fusion_agent import FusionAgent, FusionAgentConfig
from fusion_core.physics.reaction import ReactionConfig
from fusion_core.contracts.schemas import ReactionType, PropulsionMode

# D-T 반응기, 1초 타임스텝
config = FusionAgentConfig(
    reactor_id="DEMO-001",
    dt_s=1.0,
    reaction_config=ReactionConfig(
        reaction_type=ReactionType.DT,
        chamber_volume_m3=100.0,
        min_ignition_temp_kev=4.0,
    ),
)

agent = FusionAgent(config)
agent.ignite()
agent.set_mode(PropulsionMode.ELECTRIC_ONLY)
agent.set_throttle(0.9)

frames = agent.simulate(duration_s=120.0)

last = frames[-1]
print(f"최종 위상     : {last.phase.value}")
print(f"핵융합 이득 Q : {last.state.plasma.q_factor:.2f}")
print(f"총 출력       : {last.state.reaction.power_total_mw:.1f} MW")
print(f"추력          : {last.state.propulsion.thrust_n:.0f} N")
print(f"Ω_fusion      : {last.health.omega_fusion:.3f}  [{last.health.verdict}]")
print(f"감사 체인     : {len(agent._chain._blocks)} 블록")
```

---

## 핵심 물리 방정식 요약

```
핵융합 반응률:   P_density = n_D · n_T · <σv>(T) · E_fusion
출력 분배:       P_charged = P_total × f_charged
                 P_neutron = P_total × (1 - f_charged)

방열판:          P_rad = ε · σ_SB · A · T_rad⁴

중성자 플럭스:   Φ = P_n / (4π · r² · E_n)

차폐 두께:       x = ln(Φ / Φ_limit) / μ

추력(전기):      F = 2 · P_eff / (Isp · g₀)
추력(직접):      F = 2 · P_charged · η / v_e

로손 기준:       n · τ · T > 3×10²¹  [D-T, keV·s/m³]

건전성:          Ω_fusion = Σ wᵢ · Ωᵢ  ∈ [0, 1]
```

---

*"에너지는 보존되고, 열은 버려지며, 추진은 그 나머지다."*
