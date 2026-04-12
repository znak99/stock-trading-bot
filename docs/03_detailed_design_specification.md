
# 자동매매 시스템 상세설계서

## 1. 문서 개요

### 1.1 문서 목적
본 문서는 요건정의서와 기본설계서를 바탕으로, 실제 구현자가 바로 코드 작성에 들어갈 수 있도록
클래스, 상태, 이벤트, 계산 규칙, 실행 순서를 구체화한 **상세설계서(Low-Level Design)** 이다.

목적:
1. 구현 단계에서 해석 차이를 없앤다.
2. 3명의 IT 엔지니어가 이 문서만 보고도 같은 프로그램을 만들 수 있게 한다.
3. 상태 머신, 장부, 비용, 실행 루프의 세부 동작을 고정한다.
4. 단위 테스트와 통합 테스트 기준을 제공한다.

### 1.2 문서 범위
- 공통 객체 필드
- 핵심 클래스 초안
- 주문 상태 머신 상세
- 이벤트 처리 규칙
- 포지션/계좌 갱신 규칙
- 비용 반영 순서와 기본값
- 실행 루프 상세 순서
- 패키지 내 최초 생성 파일 기준
- 테스트 시나리오 기준

---

## 2. 공통 데이터 객체 상세 정의

## 2.1 `Instrument`
### 목적
시스템 전체에서 종목을 일관되게 식별하기 위한 표준 객체

### 필수 필드
- `instrument_id`
- `symbol`
- `name`
- `market`
- `asset_type`
- `sector`
- `is_etf`
- `is_active`

### 구현 메모
- `instrument_id`는 내부 고유 식별자
- `symbol`은 외부 브로커/시장 코드
- 시장 확장을 위해 `market`은 enum 또는 문자열 상수 집합으로 관리

---

## 2.2 `MarketDataSnapshot`
### 목적
특정 시점의 표준화된 시세 정보

### 필수 필드
- `snapshot_id`
- `instrument_id`
- `timestamp`
- `open_price`
- `high_price`
- `low_price`
- `close_price`
- `volume`
- `trading_value`
- `change_rate`
- `is_final`
- `session_phase`

### 구현 메모
- 장중 스냅샷과 종가 확정 스냅샷을 동일 객체로 표현
- `is_final=True`이면 종가 확정 로직 입력으로 사용 가능

---

## 2.3 `CandidateSelectionResult`
### 목적
필터 체인 통과 여부와 사유를 기록하는 객체

### 필수 필드
- `candidate_id`
- `instrument_id`
- `timestamp`
- `filter_policy_name`
- `passed`
- `passed_filters`
- `failed_filters`
- `eligibility_reason`
- `market_snapshot_ref`

### 구현 메모
- `passed_filters`, `failed_filters`는 문자열 리스트 또는 구조화된 이유 목록
- 백테스트/모의투자 분석에 필수 저장 대상

---

## 2.4 `Signal`
### 목적
전략이 생성한 표준 실행 전 신호

### 필수 필드
- `signal_id`
- `instrument_id`
- `timestamp`
- `signal_type`
- `strategy_name`
- `signal_strength`
- `decision_reason`
- `market_snapshot_ref`
- `candidate_ref`
- `target_execution_time`
- `is_confirmed`

### 구현 메모
- `signal_type`: `buy`, `sell`, `partial_sell`
- 전략은 `Signal`까지만 생성하고, 주문은 생성하지 않는다.

---

## 2.5 `ScoreResult`
### 목적
AI 점수와 후보 순위를 표준화한 객체

### 필수 필드
- `score_id`
- `instrument_id`
- `timestamp`
- `model_name`
- `model_version`
- `score_value`
- `rank`
- `feature_set_name`
- `candidate_ref`
- `score_reason_summary`

### 구현 메모
- 초기에는 순위화 용도
- 자금 배분 계산에 직접 사용하지 않음

---

## 2.6 `OrderRequest`
### 목적
실제 주문 실행 전 표준 요청 객체

### 필수 필드
- `order_request_id`
- `instrument_id`
- `timestamp`
- `side`
- `order_type`
- `quantity`
- `price`
- `time_in_force`
- `source_signal_id`
- `risk_check_ref`
- `broker_mode`
- `request_reason`

### 구현 메모
- 동일 `OrderRequest`를 재사용하지 않는다.
- 취소 후 재주문 시 반드시 새 객체를 만든다.

---

## 2.7 `OrderEvent`
### 목적
주문 상태와 체결 변화를 표현하는 표준 이벤트 객체

### 필수 필드
- `order_event_id`
- `order_request_id`
- `timestamp`
- `event_type`
- `broker_order_id`
- `filled_quantity`
- `filled_price_avg`
- `remaining_quantity`
- `event_message`
- `is_terminal`

### 구현 메모
- `filled_quantity`는 누적 체결 수량 기준 권장
- `filled_price_avg`는 누적 평균 체결가
- 저장소에 반드시 남겨야 한다.

---

## 2.8 `Position`
### 목적
보유 종목 상태 표현

### 필수 필드
- `position_id`
- `instrument_id`
- `opened_at`
- `updated_at`
- `quantity`
- `avg_entry_price`
- `current_price`
- `unrealized_pnl`
- `unrealized_pnl_rate`
- `position_status`
- `exit_policy_name`

### 구현 메모
- v1 `position_status`: `open`, `closed`
- 부분 청산 여부는 이력/거래내역으로 확인하는 방식을 권장

---

## 2.9 `AccountState`
### 목적
계좌 자산 상태 표준 객체

### 필수 필드
- `account_state_id`
- `timestamp`
- `broker_mode`
- `total_equity`
- `cash_balance`
- `available_cash`
- `market_value`
- `active_position_count`
- `max_position_limit`
- `account_status`

### 내부 확장 관리값(저장소/메모리)
- `reserved_cash`
- `reserved_sell_quantity`
- `realized_pnl`
- `accumulated_buy_commission`
- `accumulated_sell_commission`
- `accumulated_sell_tax`
- `accumulated_slippage_cost_estimate`

---

## 2.10 `RiskCheckResult`
### 목적
주문 직전 리스크 검사 결과

### 필수 필드
- `risk_check_id`
- `timestamp`
- `instrument_id`
- `order_request_preview`
- `risk_policy_name`
- `passed`
- `failure_reasons`
- `allowed_quantity`
- `allowed_capital`
- `account_state_ref`
- `position_refs`

### 구현 메모
- 주문 차단의 이유를 반드시 남긴다.
- 모의투자 분석과 운영 감사에 사용한다.

---

## 3. 핵심 클래스 상세 설계

## 3.1 `ExecutionRuntime`
### 책임
- 실행 모드별 부트스트랩
- 세션 루프 진행
- 상위 오케스트레이션

### 주요 메서드 예시
- `bootstrap()`
- `run_session()`
- `run_pre_market()`
- `run_intraday_monitor()`
- `run_market_close_process()`
- `run_next_open_execution()`
- `shutdown()`

### 의존 구성
- `SessionClock`
- `StrategyCoordinator`
- `ExecutionCoordinator`
- `PortfolioCoordinator`
- `ResultCollector`

---

## 3.2 `StrategyCoordinator`
### 책임
- 장중 후보 감시 파이프라인 실행
- 종가 확정 파이프라인 실행
- AI 점수화 파이프라인 연결

### 주요 메서드 예시
- `scan_intraday_candidates()`
- `confirm_close_candidates()`
- `rank_candidates()`
- `evaluate_exit_signals()`

---

## 3.3 `ExecutionCoordinator`
### 책임
- 주문 제출
- 브로커 이벤트 수신
- 상태 머신 반영
- 표준 `OrderEvent` 생성

### 주요 메서드 예시
- `submit_order(order_request)`
- `request_cancel(order_request_id)`
- `handle_broker_event(raw_event)`
- `normalize_event(raw_event) -> OrderEvent`

### 실거래 구현 메모
- `adapters/live/live_broker.py`는 KIS Open API를 기준으로 구현한다.
- 주문 제출/취소는 REST API를 사용한다.
- 체결 및 상태 변화는 주문체결조회 polling 결과를 `OrderEvent`로 정규화한다.
- v1에서는 웹소켓 실시간 체결 통지는 선택 확장으로 남기고 polling을 기준 구현으로 둔다.

---

## 3.4 `PortfolioCoordinator`
### 책임
- 주문 직전 리스크 검사
- 체결 이벤트 기준 장부 갱신
- 예약 자금/예약 수량 관리

### 주요 메서드 예시
- `build_order_request(signal, score_result=None)`
- `reserve_for_buy(order_request)`
- `reserve_for_sell(order_request)`
- `apply_order_event(order_event)`

---

## 3.5 `OrderStateMachine`
### 책임
- 상태 검증
- 전이 허용 여부 판단
- 다음 상태 계산

### 권장 인터페이스
- `transition(current_state, event_type) -> next_state`
- `is_terminal(state) -> bool`
- `validate_transition(current_state, event_type)`

### 구현 원칙
- if/else 중첩보다 전이 테이블 기반 구현 권장
- 테스트가 쉬워야 한다.

---

## 4. 주문 상태 머신 상세

### 4.1 상태 목록
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

### 4.2 상태 의미
#### `created`
주문 요청 생성 완료, 아직 제출 시작 전

#### `pending_submit`
제출 큐 등록, 브로커 전송 전 또는 전송 처리 중

#### `submitted`
브로커 전송 완료, 아직 접수 확인 전

#### `accepted`
브로커 접수 확인 완료

#### `partially_filled`
일부 체결

#### `filled`
전량 체결 완료, 종료 상태

#### `cancel_pending`
취소 요청 전달 후 응답 대기

#### `canceled`
취소 완료, 종료 상태

#### `rejected`
내부 또는 브로커 거절, 종료 상태

#### `expired`
주문 유효시간 종료, 종료 상태

### 4.3 기본 전이
- `created` → `pending_submit`
- `pending_submit` → `submitted`
- `submitted` → `accepted`
- `submitted` → `rejected`
- `accepted` → `partially_filled`
- `accepted` → `filled`
- `accepted` → `cancel_pending`
- `accepted` → `expired`
- `partially_filled` → `partially_filled`
- `partially_filled` → `filled`
- `partially_filled` → `cancel_pending`
- `partially_filled` → `expired`
- `cancel_pending` → `canceled`
- `cancel_pending` → `partially_filled`
- `cancel_pending` → `filled`
- `pending_submit` → `canceled`
- `pending_submit` → `rejected`

### 4.4 금지 전이
- 종료 상태 → 활성 상태 복귀
- 어떤 상태든 정정 상태로 이동
- `created` → `filled` 직접 이동
- `rejected` 된 주문 재사용

---

## 5. 이벤트 처리 상세

### 5.1 표준 이벤트 목록
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

### 5.2 이벤트 처리 핵심 원칙
1. 체결 이벤트만 포지션을 바꾼다.
2. 거절/취소/만료는 체결되지 않은 잔량만 해제한다.
3. 취소 요청 이후 늦게 도착한 체결도 유효하게 반영한다.
4. 타임아웃은 즉시 실패로 단정하지 않고 재조회 후 정규화한다.

### 5.3 이벤트별 처리 요약
#### `submit_enqueued`
- 상태: `created` → `pending_submit`
- 장부 변화: 없음

#### `submit_sent`
- 상태: `pending_submit` → `submitted`
- 장부 변화: 없음

#### `broker_accepted`
- 상태: `submitted` → `accepted`
- 장부 변화: 없음

#### `broker_rejected`
- 상태: `submitted` → `rejected`
- 장부 변화: 예약분 해제

#### `partial_fill`
- 상태: `accepted`/`partially_filled` 유지 또는 갱신
- 장부 변화: 즉시 반영

#### `full_fill`
- 상태: `accepted`/`partially_filled` → `filled`
- 장부 변화: 즉시 반영

#### `cancel_requested`
- 상태: 활성 상태 → `cancel_pending`
- 장부 변화: 없음

#### `cancel_confirmed`
- 상태: `cancel_pending` → `canceled`
- 장부 변화: 잔량 예약 해제

#### `cancel_rejected`
- 상태: 재조회 후 정규화
- 장부 변화: 재조회 전 확정 없음

#### `expired`
- 상태: `accepted`/`partially_filled` → `expired`
- 장부 변화: 잔량 예약 해제

#### `late_fill_after_cancel_request`
- 상태: `cancel_pending`에서 `partially_filled` 또는 `filled`
- 장부 변화: 즉시 반영

---

## 6. 장부 갱신 상세 규칙

## 6.1 공통 원칙
1. 실제 현금은 체결 시점에만 변경한다.
2. 주문 가능 현금은 예약 자금을 고려해 계산한다.
3. 매수 미체결은 `reserved_cash`로 관리한다.
4. 매도 미체결은 `reserved_sell_quantity`로 관리한다.
5. 부분 체결은 즉시 반영한다.

---

## 6.2 매수 주문 제출
### 변경 사항
- `cash_balance`: 변화 없음
- `available_cash`: 감소
- `reserved_cash`: 증가
- `Position`: 변화 없음

### 예약금 계산
- `expected_buy_amount = reference_price * quantity`
- 시장가/시가 주문은 보수 버퍼를 포함한 참조 가격 사용 가능

---

## 6.3 매수 부분 체결
### 변경 사항
#### `Position`
- 새 포지션 생성 또는 기존 포지션 수량 증가
- `quantity` 증가
- `avg_entry_price` 재계산
- `position_status = open`

#### `AccountState`
- `cash_balance` 감소
- `reserved_cash` 감소
- `available_cash` 추가 변화 없음
- `market_value`, `total_equity` 재계산

### 평균단가 공식
```text
new_avg =
(existing_qty * existing_avg + fill_qty * effective_buy_price)
 / (existing_qty + fill_qty)
```

---

## 6.4 매수 전량 체결
### 변경 사항
- `cash_balance` 최종 감소
- 남은 `reserved_cash` 해제
- 예약금과 실제 체결금액 차액 복원
- 신규 포지션이면 `active_position_count + 1`

---

## 6.5 매도 주문 제출
### 변경 사항
- `cash_balance`: 변화 없음
- `available_cash`: 변화 없음
- `reserved_sell_quantity`: 증가
- `Position.quantity`: 변화 없음

### 원칙
- `tradable_sell_quantity = quantity - reserved_sell_quantity`

---

## 6.6 매도 부분 체결
### 변경 사항
#### `Position`
- `quantity` 감소
- `avg_entry_price` 유지
- `reserved_sell_quantity` 감소

#### `AccountState`
- `cash_balance` 증가
- `available_cash` 증가
- `market_value`, `total_equity` 재계산

#### `realized_pnl`
```text
(effective_sell_price - avg_entry_price) * fill_qty
- sell_commission
- sell_tax
```

---

## 6.7 매도 전량 체결
### 변경 사항
- `quantity = 0`
- `reserved_sell_quantity = 0`
- `position_status = closed`
- `active_position_count - 1`
- 현금 증가와 실현손익 최종 확정

---

## 6.8 취소/만료/거절
### 매수 취소/만료/거절
- 남은 `reserved_cash` 해제
- `available_cash` 복원
- 체결분은 유지

### 매도 취소/만료/거절
- 남은 `reserved_sell_quantity` 해제
- 체결분은 유지

### 공통
- 체결되지 않은 잔량에는 비용 없음

---

## 6.9 늦은 체결
### 규칙
- 취소 요청 이후 도착한 체결도 유효 체결로 인정
- 매수면 포지션/현금 반영
- 매도면 포지션 감소/현금 증가
- 예약분 재정산
- 남은 잔량이 있으면 이후 취소 완료/만료 상태 재평가

---

## 7. 비용 모델 상세

## 7.1 공통 원칙
- 슬리피지는 체결가에 먼저 반영
- 수수료와 세금은 별도 비용으로 차감
- 평균단가는 슬리피지 반영 가격 기준
- 매수 수수료는 평균단가에 넣지 않고 별도 비용 처리
- 매도 실현손익은 매도 비용을 직접 차감

## 7.2 매수 비용 순서
1. `raw_fill_price` 확인
2. `effective_buy_price = raw_fill_price * (1 + buy_slippage_rate)`
3. `gross_buy_amount = effective_buy_price * filled_quantity`
4. `buy_commission = gross_buy_amount * buy_commission_rate`
5. `cash_balance -= gross_buy_amount + buy_commission`
6. 평균단가 재계산

## 7.3 매도 비용 순서
1. `raw_fill_price` 확인
2. `effective_sell_price = raw_fill_price * (1 - sell_slippage_rate)`
3. `gross_sell_amount = effective_sell_price * filled_quantity`
4. `sell_commission = gross_sell_amount * sell_commission_rate`
5. `sell_tax = gross_sell_amount * sell_tax_rate`
6. `net_sell_cash_inflow = gross_sell_amount - sell_commission - sell_tax`
7. `cash_balance += net_sell_cash_inflow`
8. `realized_pnl = (effective_sell_price - avg_entry_price) * fill_qty - sell_commission - sell_tax`

## 7.4 비용 파라미터
### 보수형 운영 기본값
```text
buy_commission_rate  = 0.00025
sell_commission_rate = 0.00025
sell_tax_rate        = 0.0020
buy_slippage_rate    = 0.0030
sell_slippage_rate   = 0.0015
```

### 균형형 비교 테스트값
```text
buy_commission_rate  = 0.00015
sell_commission_rate = 0.00015
sell_tax_rate        = 0.0020
buy_slippage_rate    = 0.0015
sell_slippage_rate   = 0.0007
```

## 7.5 내부 누적 비용 권장 필드
- `accumulated_buy_commission`
- `accumulated_sell_commission`
- `accumulated_sell_tax`
- `accumulated_slippage_cost_estimate`

---

## 8. 실행 루프 상세

## 8.1 상위 세션 단계

### `PRE_MARKET`
- 종목 마스터/전일 데이터 로드
- 계좌 상태 초기화
- 예약 주문 조회
- 세션 시작 로그

### `INTRADAY_MONITOR`
- 새 스냅샷 수신
- 후보군 필터 실행
- 장중 돌파 후보 감시
- 청산 신호 감시
- 필요 시 매도 주문 흐름 시작

### `MARKET_CLOSE_PROCESS`
- 종가 확정 스냅샷 생성
- 종가 확정 진입 조건 평가
- AI 점수화
- 후보 순위화
- 리스크 검사
- 다음 거래일 시가 예약 주문 생성

### `NEXT_OPEN_EXECUTION`
- 예약 주문 조회
- 다음날 시가 주문 제출
- 주문 상태 머신과 이벤트 처리 시작

## 8.2 내부 주문 이벤트 루프
1. 브로커/시뮬레이터 이벤트 수신
2. `OrderStateMachine` 전이 계산
3. 표준 `OrderEvent` 생성
4. `FillProcessor` 해석
5. `PortfolioCoordinator` 장부 갱신
6. `Infrastructure` 저장/로그 기록

---

## 9. 최초 생성 파일 목록 기준

### 9.1 1차 구현 필수 파일
```text
core/models/instrument.py
core/models/market_data_snapshot.py
core/models/candidate_selection_result.py
core/models/signal.py
core/models/score_result.py
core/models/order_request.py
core/models/order_event.py
core/models/position.py
core/models/account_state.py
core/models/risk_check_result.py

core/enums/order_state.py
core/enums/order_event_type.py

core/interfaces/broker.py
core/interfaces/strategy.py
core/interfaces/filter.py
core/interfaces/ranking_model.py
core/interfaces/exit_policy.py

execution/state_machine/order_state_machine.py
execution/services/order_manager.py
execution/services/fill_processor.py

portfolio/services/pre_trade_risk_checker.py
portfolio/services/portfolio_updater.py
portfolio/stores/position_book.py
portfolio/stores/account_state_store.py
portfolio/policies/equal_weight_allocation_policy.py

runtime/execution_runtime.py
runtime/session_clock.py
runtime/strategy_coordinator.py
runtime/execution_coordinator.py
runtime/portfolio_coordinator.py
runtime/result_collector.py

strategy/entry/breakout_swing_entry_strategy.py
strategy/exit/conservative_exit_policy.py
strategy/services/close_confirmation_engine.py
strategy/services/signal_factory.py

universe/services/candidate_selector.py
universe/policies/default_filter_policy.py

market/services/snapshot_builder.py
market/services/indicator_preprocessor.py

adapters/backtest/historical_market_data_feed.py
adapters/backtest/simulated_broker.py

infrastructure/config/config_manager.py
infrastructure/persistence/trade_repository.py
infrastructure/logging/event_logger.py

app/run_backtest.py
```

### 9.2 2차 구현 파일
- `ai/*`
- `adapters/paper/*`
- `adapters/live/*`
- `notifications/*`
- 슬리피지 고도화 모듈
- 리포트/성과 분석 모듈

### 9.3 실거래 구현 파일
- `adapters/live/live_broker.py`

---

## 10. 테스트 상세 기준

## 10.1 상태 머신 테스트
반드시 검증할 것:
- 정상 전이
- 금지 전이
- 종료 상태 복귀 금지
- `cancel_pending` 중 늦은 체결 처리

## 10.2 장부 테스트
반드시 검증할 것:
- 매수 부분 체결
- 매수 전량 체결
- 매도 부분 체결
- 매도 전량 체결
- 취소/만료/거절
- 예약 자금 해제
- 비용 반영
- 평균단가 계산

## 10.3 전략 흐름 테스트
반드시 검증할 것:
- 장중 후보 감시
- 종가 확정
- 다음날 시가 예약 주문 생성
- 청산 시그널 생성
- 최대 보유 종목 수 제한

## 10.4 통합 테스트
반드시 검증할 것:
- 종가 확정 → 예약 주문 → 다음날 시가 제출
- `OrderEvent` → 상태 머신 → 장부 갱신 흐름
- 비용 프로파일 변경 시 손익 차이 반영

---

## 11. 구현 시 주의사항

1. 전략 코드에서 브로커 객체를 직접 호출하지 않는다.
2. `OrderEvent` 없이 포지션 장부를 직접 바꾸지 않는다.
3. `available_cash`는 반드시 `cash_balance`와 `reserved_cash` 관계를 유지해야 한다.
4. 종료 상태 주문을 다시 재사용하지 않는다.
5. 테스트 없이 상태 머신/장부 규칙을 변경하지 않는다.
6. 보수형 비용 프로파일을 운영 기본값으로 유지한다.
7. AI 점수는 초기에는 순위화에만 사용한다.
8. v1에서는 정정 주문을 넣지 않는다.

---

## 12. 문서 종료 선언
본 문서는 구현자가 그대로 코딩을 시작할 수 있도록 만든 상세 기준 문서이다.
구현 중 해석 차이가 생기면 본 문서의 상태, 이벤트, 장부, 비용, 실행 순서를 우선 기준으로 삼는다.
추가 고도화는 본 문서의 확장 슬롯을 이용해 수행한다.
