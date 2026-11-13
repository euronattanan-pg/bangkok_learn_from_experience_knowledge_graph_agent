FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lfe ./lfe
COPY static ./static
RUN useradd --create-home app && mkdir /data && chown app:app /data
USER app
ENV LFE_DATA_DIR=/data
EXPOSE 8000
CMD ["python", "-m", "lfe.server"]
