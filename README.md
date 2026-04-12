# Stock Trading Bot

국내 주식 자동매매 및 종목 추천 시스템입니다.

이 저장소는 아래 원칙을 기준으로 시작합니다.

- 문서 우선 개발: `docs/01~04`를 기준으로 구조와 설정을 고정합니다.
- 공통 코어 유지: 백테스트, 모의투자, 실거래가 같은 코어를 공유하도록 설계합니다.
- 상태/장부 무결성 보호: 주문 상태 머신과 `OrderEvent` 기반 장부 갱신을 전제로 합니다.

## 디렉토리 구조

```text
.
├─ configs/
├─ data/
├─ docs/
├─ notebooks/
├─ scripts/
├─ src/
│  └─ stock_trading_bot/
└─ tests/
```

`src/stock_trading_bot/` 아래 패키지는 기본설계서의 상위 8모듈 구조를 따릅니다.

## 빠른 시작

1. 가상환경 생성

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. 개발 의존성 설치

```powershell
pip install -e .[dev]
```

3. 환경변수 파일 준비

```powershell
Copy-Item .env.example .env
```

4. 기본 설정 확인

```powershell
Get-Content configs/base.yaml
```

5. 단위 테스트 실행

```powershell
pytest -q
```

## Docker

현재 컨테이너 기준 Python 버전은 `3.11`입니다.
이유는 `pyproject.toml`의 `requires-python = ">=3.11,<3.14"` 범위 안에서,
현재 정적 도구 설정(`ruff`, `mypy`)이 `3.11`을 기준으로 맞춰져 있기 때문입니다.

1. 이미지 빌드

```powershell
docker build -t stock-trading-bot .
```

2. 기본 실행

```powershell
docker run --rm stock-trading-bot
```

기본 명령은 패키지 설치 여부와 버전을 확인합니다. 실제 백테스트 실행은 아래 CLI를 사용합니다.

테스트 실행은 다음 명령을 사용합니다.

```powershell
docker run --rm stock-trading-bot pytest -q
```

## 설정 파일

- `configs/base.yaml`: 공통 런타임, 로깅, 프로파일 선택 기본값
- `configs/modes/backtest.yaml`: 백테스트 모드 기본 설정
- `configs/modes/live.yaml`: KIS Open API 기반 실거래 브로커 설정
- `configs/strategy/breakout_swing_v1.yaml`: 돌파형 스윙 전략 기본값
- `configs/risk/conservative_risk_v1.yaml`: 보수형 리스크 정책
- `configs/costs/conservative.yaml`: 운영 기본 비용 프로파일
- `configs/market/kr_stock.yaml`: 국내 주식 시장 규칙 기본값
- `configs/experiments/*.yaml`: 파라미터 실험 정의 파일

`configs/base.yaml`의 `universe` 섹션은 기본 필터 정책과 최소 거래대금/거래량 임계값을 관리합니다.
`configs/strategy/breakout_swing_v1.yaml`의 `ai_scoring` 섹션은 CoreFeatureSet 기반 1차 점수화 모델 설정을 관리합니다.
`.env.example`의 `BROKER_*` 변수는 KIS Open API 실거래 연동과 주문체결 polling 정규화에 사용합니다.

## 백테스트 실행

런타임 오케스트레이션과 CLI 엔트리포인트가 구현되어 있습니다.

```powershell
python -m stock_trading_bot.app.run_backtest
```

데이터 디렉토리를 직접 지정하려면 다음처럼 실행합니다.

```powershell
python -m stock_trading_bot.app.run_backtest --data-dir tests/fixtures/market
```

실행 결과는 표준 출력으로 요약됩니다.

- `initial_equity`, `final_equity`, `total_pnl`, `return_rate`
- `realized_pnl`, `unrealized_pnl`
- `buy_commission`, `sell_commission`, `sell_tax`, `slippage_estimate`
- 주문 수, 체결 이벤트 수, 최종 포지션 수

## 파라미터 실험

설정 파일 기반 반복 실험도 지원합니다.

```powershell
python -m stock_trading_bot.app.run_parameter_experiments `
  --experiment-config configs/experiments/breakout_swing_entry_sensitivity.yaml `
  --data-dir tests/fixtures/market
```

실험 실행 후에는 각 run별 백테스트 결과와 로그가 별도 디렉토리에 저장되고,
실험 루트에는 `comparison.json`, `comparison.csv`가 생성됩니다.

## 현재 상태

현재 구현 범위는 다음까지 반영되어 있습니다.

- 프로젝트 초기 구조 및 실행 환경 설정
- 공통 데이터 객체
- 핵심 Enum 및 인터페이스 계약
- 주문 상태 머신
- 포지션/계좌 장부 엔진과 주문 전 리스크 검사
- 백테스트용 OHLCV 로더, 지표 전처리, 시세 스냅샷 생성
- UniverseSelection 필터 정책과 후보 선정 서비스
- 돌파형 스윙 진입 전략, 종가 확정 엔진, Signal 생성기
- 보수형 청산 정책
- CoreFeatureSet 기반 AI Scoring 1차 구현과 후보 순위 정렬
- SimulatedBroker와 실행 서비스(OrderManager, FillProcessor)
- Runtime 실행 엔진(SessionClock, Coordinators, ResultCollector)
- 백테스트 애플리케이션 엔트리포인트(`python -m stock_trading_bot.app.run_backtest`)
- End-to-End 백테스트 흐름(필터 -> 전략 -> 주문 -> 체결 -> 청산 -> 결과 요약 출력)
- 설정 파일 기반 파라미터 실험 반복 실행 및 결과 비교
- KIS Open API 기반 `LiveBroker` REST 인증, 주문/취소, 체결조회 polling 정규화

실거래 소액 주문 검증은 실제 KIS 계좌 자격증명이 준비되어야 마무리할 수 있습니다.
