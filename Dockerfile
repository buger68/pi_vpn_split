FROM python:3-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    wireguard-tools \
    iproute2 \
    nftables \
    openresolv \
    procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 53/udp 5353/udp 3001/tcp 3000/tcp

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "main.py"]