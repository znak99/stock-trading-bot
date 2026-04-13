
# 자동매매 시스템 기본설계서

## 1. 문서 개요

### 1.1 문서 목적
본 문서는 요건정의서를 구현 가능한 시스템 구조로 변환한 **기본설계서(High-Level Design)** 이다.
목적은 다음과 같다.

1. 시스템 전체 골격을 정의한다.
2. 모듈 간 책임 경계와 데이터 흐름을 고정한다.
3. 백테스트/모의투자/실거래가 가능한 공통 코어 구조를 정의한다.
4. 개발 도중 아키텍처 방향이 흔들리지 않도록 상위 설계 기준을 제공한다.

### 1.2 문서 범위
본 문서는 아래를 다룬다.

- 시스템 아키텍처 스타일
- 상위 8모듈 구조
- 공통 데이터 객체 구조
- 실행 엔진 구조
- 상태 관리 구조의 책임 경계
- 백테스트/모의투자/실거래 공통화 원칙
- 프로젝트 패키지/폴더 구조

### 1.3 문서 관계
- 요건정의서: 무엇을 만들 것인가
- 기본설계서: 시스템을 어떤 구조로 나눌 것인가
- 상세설계서: 각 요소를 정확히 어떻게 구현할 것인가

---

## 2. 아키텍처 개요

### 2.1 아키텍처 스타일
본 시스템은 다음 구조를 채택한다.

> **계층형 + 플러그인형 + 내부 이벤트 처리 혼합형**

구성 의미:
- 전체 구조는 계층형으로 이해하기 쉽게 유지한다.
- 시장, 브로커, 전략, 필터, AI, 비용 정책 등은 플러그인형으로 교체 가능하게 한다.
- 주문/체결/포지션과 같은 상태 변화는 내부 이벤트 기반으로 안정적으로 처리한다.

### 2.2 채택 이유
1. 초기에 보수적이고 설명 가능한 구조가 필요하다.
2. 장기적으로는 시장/브로커/전략/AI 확장이 가능해야 한다.
3. 주문/체결/포지션 상태 꼬임을 막기 위해 내부 이벤트 처리가 필요하다.
4. 완전 이벤트 버스 기반보다 구현과 이해의 균형이 좋다.

### 2.3 설계 원칙
- 상위 흐름은 오케스트레이터가 제어한다.
- 하위 주문/체결 흐름은 이벤트와 상태 머신으로 제어한다.
- 전략은 주문을 직접 실행하지 않는다.
- 주문 상태 변경은 반드시 상태 머신을 통해서만 일어난다.
- 포지션/계좌 장부는 체결 이벤트만 기준으로 변경된다.

---

## 3. 상위 시스템 구조

### 3.1 상위 8모듈 구성
본 시스템의 상위 구조는 다음 8모듈로 구성한다.

1. `Application`
2. `MarketData`
3. `UniverseSelection`
4. `StrategyEngine`
5. `AIScoring`
6. `Execution`
7. `PortfolioRisk`
8. `Infrastructure`

### 3.2 상위 모듈 관계 개요
```text
Application
 ├─ MarketData
 ├─ UniverseSelection
 ├─ StrategyEngine
 ├─ AIScoring
 ├─ PortfolioRisk
 ├─ Execution
 └─ Infrastructure
```

### 3.3 설계 원칙
- 상위에서는 8모듈만 명확히 노출한다.
- 세부 복잡성은 각 모듈 내부 서브컴포넌트에 숨긴다.
- 상위 모듈은 책임이 겹치지 않아야 한다.
- 상위 모듈 간 데이터 교환은 공통 객체를 통해서만 이뤄진다.

---

## 4. 상위 8모듈 정의

## 4.1 `Application`
### 역할
- 시스템 시작/종료
- 실행 모드 결정 (`backtest`, `paper`, `live`)
- 장 시작/장중/장마감/다음날 시가 실행 스케줄 제어
- 상위 실행 순서 제어

### 포함 서브컴포넌트
- `TradingApplication`
- `RuntimeManager`
- `ScheduleCoordinator`
- `ModeResolver`

### 비포함 책임
- 전략 계산
- 주문 실행
- 장부 계산

---

## 4.2 `MarketData`
### 역할
- 종목 마스터 조회
- 시세/거래량/거래대금 수집
- 표준 시세 스냅샷 생성
- 기술지표 계산용 원천 데이터 제공
- 시장 컨텍스트 데이터 제공

### 포함 서브컴포넌트
- `MarketDataProvider`
- `SnapshotBuilder`
- `IndicatorPreprocessor`
- `MarketContextProvider`
- `InstrumentRepository`

### 비포함 책임
- 필터 통과 여부 판단
- 매수/매도 신호 생성
- 주문 실행

---

## 4.3 `UniverseSelection`
### 역할
- 전체 종목군 정의
- 계층형 필터 적용
- 후보 선정 및 사유 기록

### 포함 서브컴포넌트
- `UniverseProvider`
- `EligibilityEvaluator`
- `Filter`
- `FilterChain`
- `FilterPolicy`
- `CandidateSelector`

### 비포함 책임
- 최종 진입 신호 생성
- 주문 수량 계산
- AI 점수 계산

---

## 4.4 `StrategyEngine`
### 역할
- 장중 돌파 후보 감시
- 종가 확정 조건 평가
- 매수/매도/부분매도 신호 생성
- 청산 정책 적용

### 포함 서브컴포넌트
- `Strategy`
- `BreakoutSwingEntryStrategy`
- `CloseConfirmationEngine`
- `ExitPolicy`
- `ConservativeExitPolicy`
- `SignalFactory`

### 비포함 책임
- 주문 제출
- 브로커 연동
- 장부 계산

---

## 4.5 `AIScoring`
### 역할
- 후보용 피처 생성
- AI 점수화
- 후보 우선순위 정렬

### 포함 서브컴포넌트
- `FeatureBuilder`
- `CoreFeatureSetBuilder`
- `RankingModel`
- `BasicRankingModel`
- `AdvancedRankingModel`
- `ScoreCalibrator`
- `CandidateRanker`

### 비포함 책임
- 최종 주문 비중 결정
- 브로커 호출
- 포지션 장부 변경

---

## 4.6 `Execution`
### 역할
- 주문 요청 수신
- 브로커 전송
- 주문 상태 머신 운영
- 체결/취소/거절 이벤트 해석
- 표준 `OrderEvent` 생성

### 포함 서브컴포넌트
- `Broker`
- `PaperBroker`
- `LiveBroker`
- `OrderManager`
- `OrderStateMachine`
- `FillProcessor`
- `ExecutionService`

### 비포함 책임
- 전략 판단
- 리스크 정책 결정
- 포지션 직접 계산

---

## 4.7 `PortfolioRisk`
### 역할
- 포지션 장부 관리
- 계좌 상태 관리
- 예약 자금/예약 수량 관리
- 주문 전 리스크 재검사
- 자금 배분 정책 적용
- 체결 후 포지션/계좌 반영
- 운영 안전장치와 연결되는 주문 차단 기준 제공

### 포함 서브컴포넌트
- `PositionBook`
- `AccountStateStore`
- `AllocationPolicy`
- `EqualWeightAllocationPolicy`
- `WeightedScoreAllocationPolicy`
- `RiskPolicy`
- `PreTradeRiskChecker`
- `PortfolioUpdater`

### 비포함 책임
- 브로커 API 호출
- 전략 신호 생성
- 원천 시세 수집

---

## 4.8 `Infrastructure`
### 역할
- 설정 로딩
- 객체 저장
- 이벤트 로그 기록
- 알림
- 감사 추적
- 결과 저장

### 포함 서브컴포넌트
- `ConfigManager`
- `TradeRepository`
- `MarketDataRepository`
- `EventLogger`
- `AlertNotifier`
- `AuditTrailRecorder`

### 비포함 책임
- 전략 판단
- 주문 실행
- 장부 계산 로직의 본체

---

## 5. 공통 데이터 계약

### 5.1 공통 객체 목록
본 시스템은 아래 10개 공통 객체를 모듈 간 표준 계약으로 사용한다.

1. `Instrument`
2. `MarketDataSnapshot`
3. `CandidateSelectionResult`
4. `Signal`
5. `ScoreResult`
6. `OrderRequest`
7. `OrderEvent`
8. `Position`
9. `AccountState`
10. `RiskCheckResult`

### 5.2 공통 객체 사용 원칙
- 모듈 간 직접 내부 구조를 노출하지 않는다.
- 반드시 표준 객체로 입출력을 주고받는다.
- 공통 객체의 필드는 상세설계서 기준으로 구현한다.
- 각 모듈은 공통 객체의 의미를 변경하지 않는다.

### 5.3 설계 이유
- 백테스트/모의투자/실거래 공통 코어 유지
- 전략/주문/장부 결합도 감소
- 테스트와 저장 구조 단순화
- 향후 브로커/시장/전략 교체 용이

---

## 6. 주문 상태 관리 구조

### 6.1 상태 머신 채택 원칙
주문은 반드시 상태 머신으로 관리한다.
상태 목록:

- `created`
- `pending_submit`
- `submitted`
- `accepted`
- `partially_filled`
- `filled`
- `cancel_pending`
- `canceled`
- `rejected`
- `expired`

### 6.2 종료 상태
- `filled`
- `canceled`
- `rejected`
- `expired`

### 6.3 이벤트 표준
주문 상태 전이를 일으키는 표준 이벤트:

- `submit_enqueued`
- `submit_sent`
- `submit_timeout`
- `broker_accepted`
- `broker_rejected`
- `partial_fill`
- `full_fill`
- `cancel_requested`
- `cancel_confirmed`
- `cancel_rejected`
- `expired`
- `canceled_before_submit`
- `internal_rejected`
- `late_fill_after_cancel_request`

### 6.4 기본 구조 원칙
- 상태 전이 검사는 선언적 규칙 또는 테이블 기반으로 구현 가능해야 한다.
- 종료 상태 주문은 다시 활성 상태로 복귀하지 않는다.
- v1은 정정 주문을 지원하지 않는다.
- 향후 정정 주문 상태 확장을 위한 슬롯은 유지한다.

---

## 7. 실행 엔진 구조

### 7.1 실행 구조 원칙
본 시스템은 **단일 엔진 통합형 + 내부 이벤트 구조**를 사용한다.

의미:
- 백테스트, 모의투자, 실거래가 동일 코어를 공유한다.
- 차이는 주로 데이터 공급자와 브로커에서 흡수한다.
- 상위는 스케줄 루프가 제어한다.
- 내부 주문 흐름은 이벤트 처리로 관리한다.

### 7.2 실행 모드
- `backtest`
- `paper`
- `live`

### 7.3 세션 단계
- `PRE_MARKET`
- `INTRADAY_MONITOR`
- `MARKET_CLOSE_PROCESS`
- `NEXT_OPEN_EXECUTION`

### 7.4 실행기 구성
- `ExecutionRuntime`
- `SessionClock`
- `StrategyCoordinator`
- `ExecutionCoordinator`
- `PortfolioCoordinator`
- `ResultCollector`

### 7.5 상위 실행 순서
1. 장 시작 전 준비
2. 장중 데이터 수신 및 후보 감시
3. 종가 확정 처리
4. 예약 주문 생성
5. 다음날 시가 주문 실행
6. 주문/체결 이벤트 반영
7. 결과 저장

---

## 8. 상위 데이터 흐름

### 8.1 진입 흐름
```text
MarketDataFeed
→ MarketDataSnapshot
→ UniverseSelection
→ CandidateSelectionResult
→ StrategyEngine
→ Signal
→ AIScoring
→ ScoreResult
→ PortfolioRisk
→ OrderRequest
→ Execution
→ OrderEvent
→ PortfolioRisk
```

### 8.2 청산 흐름
```text
MarketDataFeed
→ StrategyEngine.ExitPolicy
→ Signal(sell/partial_sell)
→ PortfolioRisk
→ OrderRequest
→ Execution
→ OrderEvent
→ PortfolioRisk
```

### 8.3 예약 주문 흐름
```text
MARKET_CLOSE_PROCESS
→ 종가 확정
→ 후보 정렬
→ 리스크 검사
→ 다음 거래일 시가 예약 주문 생성
→ NEXT_OPEN_EXECUTION
→ 실제 OrderRequest 제출
```

### 8.4 흐름 원칙
- 전략은 신호까지만 만든다.
- 주문 수량/비중 결정은 `PortfolioRisk`가 담당한다.
- 상태 변화의 진실은 `Execution`이 만든 `OrderEvent`이다.
- 포지션/계좌 갱신은 `PortfolioRisk`가 수행한다.

### 8.5 운영 안전장치
- 일일 손실 제한은 당일 시작 자산 대비 손실률 기준으로 동작한다.
- 일일 손실 제한 발동 시 신규 진입 주문은 차단하고 청산 주문은 허용할 수 있다.
- 동일 종목/동일 방향의 활성 주문은 중복 제출하지 않는다.
- 이상 상태 감지 시 전체 주문 흐름을 정지한다.
- 차단 및 정지 결과는 `Infrastructure`의 알림 시스템으로 전달한다.

---

## 9. 백테스트 / 모의투자 / 실거래 공통화 구조

### 9.1 공통 코어
아래는 세 모드가 공유한다.

- 공통 객체
- 전략 엔진
- 필터 구조
- AI 점수화 구조
- 주문 상태 머신
- 포트폴리오 장부 로직
- 비용 모델
- 리스크 정책

### 9.2 모드별 차이점
#### 백테스트
- `HistoricalMarketDataFeed`
- `SimulatedBroker`

#### 모의투자
- `RealtimeMarketDataFeed`
- `PaperBroker`

#### 실거래
- `RealtimeMarketDataFeed`
- `LiveBroker`
- v1 실거래 브로커는 KIS Open API를 기준으로 구현한다.
- 체결 이벤트는 REST 주문체결조회 polling 결과를 표준 `OrderEvent`로 정규화한다.

### 9.3 설계 원칙
- 전략/장부/비용 로직은 동일해야 한다.
- 입출력 어댑터만 다르게 둔다.
- 실시간 모드에서도 공통 이벤트 구조를 유지한다.

---

## 10. 장부 설계 원칙

### 10.1 현금 관리
- `cash_balance`: 실제 체결 시점에만 변한다.
- `available_cash`: 예약 자금을 제외한 주문 가능 현금
- `reserved_cash`: 매수 미체결 잔량 예약금
- `reserved_sell_quantity`: 매도 잠금 수량

### 10.2 포지션 관리
- `quantity`: 보유 수량
- `avg_entry_price`: 이동평균단가
- 부분 체결은 즉시 반영
- 매도 체결 시 남은 수량의 평균단가는 유지

### 10.3 비용 반영
- 슬리피지는 체결가에 흡수
- 수수료/세금은 별도 비용 차감
- 보수형과 균형형 프로파일을 설정으로 관리

### 10.4 리스크 검사
- 주문 직전 리스크 재검사는 반드시 수행한다.
- 후보 선정 단계의 필터와 주문 직전 리스크 검사는 역할이 다르다.

---

## 11. 패키지 / 폴더 구조

### 11.1 최상위 구조
```text
stock_trading_bot/
├─ pyproject.toml
├─ README.md
├─ .env.example
├─ configs/
├─ data/
├─ docs/
├─ scripts/
├─ src/
├─ tests/
└─ notebooks/
```

### 11.2 `src/stock_trading_bot/` 구조
```text
src/stock_trading_bot/
├─ core/
├─ runtime/
├─ market/
├─ universe/
├─ strategy/
├─ ai/
├─ execution/
├─ portfolio/
├─ infrastructure/
├─ adapters/
└─ app/
```

### 11.3 각 패키지의 의미
- `core`: 공통 모델, enum, interface, 타입, 예외
- `runtime`: 상위 실행 흐름과 오케스트레이션
- `market`: 시장 데이터와 지표 전처리
- `universe`: 필터와 후보 선정
- `strategy`: 진입/청산 전략
- `ai`: 피처와 AI 점수화
- `execution`: 주문/체결/브로커/상태 머신
- `portfolio`: 포지션, 계좌, 리스크, 자금 배분
- `infrastructure`: 설정, 저장, 로그, 알림
- `adapters`: backtest / paper / live 입출력 차이 흡수
- `app`: 실행 진입점

### 11.4 구조 채택 원칙
- `core`에는 공통 계약만 둔다.
- 비즈니스 로직은 도메인 패키지에 둔다.
- 외부 연결은 `adapters`로 모은다.
- 상위 조립은 `runtime`에서 수행한다.
- 설정은 코드 밖 `configs/`에서 관리한다.

---

## 12. 설정 구조

### 12.1 기본 구조
```text
configs/
├─ base.yaml
├─ experiments/
├─ modes/
├─ strategy/
├─ risk/
├─ costs/
└─ market/
```

### 12.2 주요 파일 예시
- `modes/backtest.yaml`
- `modes/paper.yaml`
- `modes/live.yaml`
- `strategy/breakout_swing_v1.yaml`
- `experiments/breakout_swing_entry_sensitivity.yaml`
- `experiments/advanced_stack_validation.yaml`
- `risk/conservative_risk_v1.yaml`
- `costs/conservative.yaml`
- `costs/balanced.yaml`
- `market/kr_stock.yaml`
- `market/us_stock.yaml`
- `market/crypto.yaml`

### 12.3 설계 원칙
- 운영 기본값과 비교 테스트값을 분리한다.
- 전략/리스크/비용/시장 설정을 독립적으로 관리한다.
- 같은 코드로 설정만 바꿔 실험 가능해야 한다.

---

## 13. 테스트 구조 개요

### 13.1 테스트 분류
- `unit`
- `integration`
- `simulation`
- `fixtures`

### 13.2 테스트 원칙
- 상태 머신은 단위 테스트 필수
- 장부 갱신 규칙은 단위 테스트 필수
- 종가 확정 → 다음날 시가 실행 흐름은 통합 테스트 필수
- 백테스트/모의투자 엔진 흐름은 시뮬레이션 테스트 필수

---

## 14. v1 구현 우선순위 원칙

### 14.1 1차 우선 구현
- 공통 모델
- enum / interface
- 상태 머신
- 장부 갱신기
- 실행 런타임 최소 골격
- 백테스트용 데이터 공급자/브로커
- 돌파형 스윙 전략
- 보수형 청산 정책
- 설정 파일

### 14.2 2차 확장 구현
- AI 점수화 고도화
- paper/live 브로커
- 알림/감사추적 확장
- 슬리피지 고도화
- 리포트 시스템

---

## 15. 개발 중 반드시 지켜야 할 아키텍처 기준

1. `StrategyEngine`은 주문을 직접 호출하지 않는다.
2. `Execution`만 주문 상태와 체결의 진실을 관리한다.
3. `PortfolioRisk`만 장부를 변경한다.
4. `Infrastructure`는 비즈니스 판단을 하지 않는다.
5. 백테스트/모의투자/실거래 코어를 분기별로 따로 복제하지 않는다.
6. 공통 객체 의미를 모듈별로 다르게 해석하지 않는다.
7. 설정값은 코드 안에 하드코딩하지 않고 설정 파일로 관리한다.

---

## 16. 문서 종료 선언
본 문서는 본 프로젝트의 상위 시스템 구조 기준 문서이다.
구현 중 구조 변경이 필요해 보일 경우에도, 먼저 본 문서의 책임 분리 원칙과 데이터 흐름 원칙을 검토해야 한다.
상세 구현은 상세설계서를 따른다.
