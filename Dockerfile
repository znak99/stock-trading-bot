FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY configs ./configs
COPY docs ./docs
COPY tests ./tests
COPY .env.example ./

RUN pip install --upgrade pip \
    && pip install -e .[dev]

CMD ["python", "-c", "import stock_trading_bot; print(f'stock_trading_bot {stock_trading_bot.__version__}')"]

