# Stock Trading Bot

국내 주식 자동매매 및 종목 추천 시스템의 초기 프로젝트 골격입니다.

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

5. 초기 구조 확인

```powershell
Get-ChildItem src/stock_trading_bot
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

현재 애플리케이션 엔트리포인트는 아직 구현되지 않았기 때문에, 컨테이너 기본 명령은 패키지 설치 여부와 버전을 확인하는 수준으로만 구성되어 있습니다.

## 설정 파일

- `configs/base.yaml`: 공통 런타임, 로깅, 프로파일 선택 기본값
- `configs/modes/backtest.yaml`: 백테스트 모드 기본 설정
- `configs/strategy/breakout_swing_v1.yaml`: 돌파형 스윙 전략 기본값
- `configs/risk/conservative_risk_v1.yaml`: 보수형 리스크 정책
- `configs/costs/conservative.yaml`: 운영 기본 비용 프로파일
- `configs/market/kr_stock.yaml`: 국내 주식 시장 규칙 기본값

## 현재 상태

현재 단계는 프로젝트 구조 및 설정 파일 초기화입니다.
실제 런타임, 상태 머신, 장부, 브로커 구현은 상세설계서의 우선순위에 따라 이후 단계에서 추가합니다.
`tests/` 디렉토리는 생성되어 있지만 실제 테스트 코드는 아직 추가되지 않았습니다.
