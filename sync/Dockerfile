FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir PyMySQL==1.1.1
COPY comun/ ./comun/
COPY sync/sync.py .
RUN useradd -r -u 1001 appuser
USER appuser
CMD ["python", "-u", "sync.py"]
