FROM python:3.13-slim@sha256:bb2988715db2cf7ace7b53f38f3cffbef7c7046a656bee66245eb0ed386e2e81
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY moderation ./moderation
ENV PYTHONPATH=/app/moderation
COPY moderator.py operations.py digest.py ./
USER 1001:1001
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["python", "moderator.py"]
CMD ["serve"]
