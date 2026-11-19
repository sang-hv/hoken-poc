# PostgreSQL 16 + pgvector (vector search) + pg_bigm (từ khoá tiếng Nhật) cho chế độ local / một VM.
FROM pgvector/pgvector:pg16
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential postgresql-server-dev-16 git ca-certificates \
 && git clone --depth 1 https://github.com/pgbigm/pg_bigm.git /tmp/pg_bigm \
 && make -C /tmp/pg_bigm USE_PGXS=1 && make -C /tmp/pg_bigm USE_PGXS=1 install \
 && rm -rf /tmp/pg_bigm \
 && apt-get purge -y build-essential postgresql-server-dev-16 git && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*
COPY init.sql /docker-entrypoint-initdb.d/10-extensions.sql
