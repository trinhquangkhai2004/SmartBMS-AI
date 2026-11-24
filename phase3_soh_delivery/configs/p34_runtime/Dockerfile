FROM pbl5-rtbatt-dependencies:d11-r1
USER root
COPY requirements-linux-amd64.lock /app/p34-requirements.lock
RUN python -m pip install --no-cache-dir --index-url https://pypi.org/simple --only-binary=:all: --require-hashes -r /app/p34-requirements.lock \
    && python -m pip check
USER 1000:1000
ENTRYPOINT ["python"]
