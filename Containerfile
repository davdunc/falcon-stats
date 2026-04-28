FROM registry.fedoraproject.org/fedora:44

LABEL maintainer="David Duncan <davdunc>"
LABEL description="falcon-stats: Trading statistics engine with DynamoDB persistence"

WORKDIR /app

# Install Python and dependencies on Fedora
RUN dnf install -y python3 python3-pip && dnf clean all
COPY pyproject.toml .
RUN python3 -m pip install --no-cache-dir boto3 python-dotenv openpyxl

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
