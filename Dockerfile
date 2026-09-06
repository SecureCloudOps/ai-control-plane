FROM python:3.12-slim

WORKDIR /app
COPY control-plane/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY control-plane/router.py .

EXPOSE 5000
CMD ["python", "-u", "router.py"]
