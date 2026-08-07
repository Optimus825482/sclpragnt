FROM python:3.11-slim
WORKDIR /app
COPY server.py .
RUN mkdir -p /data
EXPOSE 8010
CMD ["python", "server.py"]
