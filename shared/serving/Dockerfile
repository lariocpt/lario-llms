FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir aiohttp==3.14.4
WORKDIR /app
COPY panel.py /app/panel.py
COPY web /app/web
USER 1000:1000
EXPOSE 9670
CMD ["python", "/app/panel.py"]
