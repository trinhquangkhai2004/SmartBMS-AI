FROM docker.io/library/python@sha256:e8c69d86735f6df3efa06b324694fe51f0422785f83a3bd463052636c2421944 AS dependencies

ENV PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1 OPENBLAS_NUM_THREADS=1
WORKDIR /app
COPY conversion/requirements-linux-amd64.lock /app/requirements-linux-amd64.lock
RUN python -m pip install --index-url https://pypi.org/simple --no-cache-dir --only-binary=:all: --require-hashes -r /app/requirements-linux-amd64.lock \
    && python -m pip check
USER 1000:1000

FROM dependencies AS production
COPY scripts/audit_rt_batt_source.py conversion/secure_source_converter.py /app/
ENTRYPOINT ["python", "/app/secure_source_converter.py"]
