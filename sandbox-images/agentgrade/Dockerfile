# ── Temel imaj ────────────────────────────────────────────
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# ── Sistem paketleri ──────────────────────────────────────
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    g++ \
    openjdk-21-jdk \
    && rm -rf /var/lib/apt/lists/*

# ── Python bağımlılığı ────────────────────────────────────
RUN pip3 install psutil --break-system-packages

# ── Uygulama dosyaları ────────────────────────────────────
WORKDIR /app
COPY . .

# ── /tmp izinleri (read_only modda tmpfs buraya mount edilir)
RUN mkdir -p /tmp && chmod 1777 /tmp

# ── Port ──────────────────────────────────────────────────
EXPOSE 8080

# ── Root olmayan kullanıcıyla çalıştır (güvenlik) ─────────
RUN useradd -m -u 1001 sandbox
USER sandbox

# ── Başlatma ──────────────────────────────────────────────
CMD ["python3", "api/server.py", "--host", "0.0.0.0", "--port", "8080"]
