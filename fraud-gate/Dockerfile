FROM python:3.12.10-slim-bookworm

# Online scoring predicts one row at a time; per-thread OpenMP teams only oversubscribe the CPU
# (10-way p50 136 ms -> 65 ms). Override OMP_NUM_THREADS for batch training inside the image.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 \
    MODEL_ARTIFACT_PATH=/artifacts/creditcard_hgb.joblib

WORKDIR /service
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 gate \
    && mkdir -p /artifacts \
    && chown gate:gate /artifacts

COPY app ./app
COPY training ./training
USER gate
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
