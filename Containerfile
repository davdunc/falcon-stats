FROM python:3.13-slim

LABEL maintainer="David Duncan <davdunc>"
LABEL description="falcon-stats: Trading statistics engine with DynamoDB persistence"

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir boto3 python-dotenv openpyxl

# Copy application
COPY falcon_stats/ falcon_stats/

# Default environment
ENV FALCON_TRADES_TABLE=falcon-trades
ENV AWS_DEFAULT_REGION=us-east-2
ENV TRADE_REVIEW_PATH=/data/Trade_Review

# Mount points:
#   /data/Trade_Review — DAS Trader CSV exports
#   /root/.aws — AWS credentials (IAM roles preferred)
VOLUME ["/data/Trade_Review", "/root/.aws"]

ENTRYPOINT ["python3", "-m", "falcon_stats.cli"]
CMD ["--help"]
