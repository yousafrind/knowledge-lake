# UNVERIFIED image. Build and run on a GPU host; expose the port privately only.
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04
RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip install "mineru[all]" fastapi uvicorn python-multipart
COPY app.py /app/app.py
WORKDIR /app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "9000"]
