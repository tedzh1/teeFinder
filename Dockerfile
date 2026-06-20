FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install the package (and its deps). README is referenced by pyproject.
COPY pyproject.toml README.md ./
COPY teefinder ./teefinder
RUN pip install --no-cache-dir .

# config/ and data/ are provided at runtime via volumes (see docker-compose.yml).
EXPOSE 8000

# Default command runs the web app; the scraper service overrides this.
CMD ["teefinder", "web", "--host", "0.0.0.0", "--port", "8000"]
