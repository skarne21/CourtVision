# CourtVision API image.
# Model artifacts + nba_data.db are gitignored — run `python Backend/scraper.py`
# locally BEFORE building so they exist in Backend/ to be copied in.
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY Backend/ .
EXPOSE 8000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
