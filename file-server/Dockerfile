# File Server Dockerfile - Production
FROM python:3.12-slim

LABEL maintainer="Computer Use File Server"
LABEL description="HTTP file server for Computer Use outputs"
LABEL version="1.0.0"

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .
COPY mcp_tools.py .

# MCP API Key for authorization
ENV MCP_API_KEY=dockerai-mcp-a673c7ee472b8d2ace6c6809ed9e08fd

# Expose port
EXPOSE 8081

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8081/health')"

# Run uvicorn (production mode, no reload)
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8081", "--workers", "2"]
