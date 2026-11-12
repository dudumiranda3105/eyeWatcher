# Uma imagem so para todos os servicos Python; cada um muda apenas o `command`.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt

# Sem root: os volumes nomeados herdam o dono destas pastas.
RUN useradd --uid 10001 --create-home eyewatcher \
    && mkdir -p /data/datasets /data/models \
    && chown -R eyewatcher:eyewatcher /data

COPY eyewatcher ./eyewatcher
USER eyewatcher
