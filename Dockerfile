FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data BACKUP_DIR=/backups
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && groupadd -g 1000 planner && useradd -u 1000 -g 1000 -M planner
COPY app ./app
COPY manage.py .
RUN chmod -R a+rX /app/app && chmod a+r /app/manage.py
USER 1000:1000
RUN python -c "import app; import app.worker; from pathlib import Path; Path('/app/manage.py').read_text()"
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "2", "--timeout", "60", "app:create_app()"]
