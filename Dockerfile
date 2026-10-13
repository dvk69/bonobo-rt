FROM python:3.12-slim

WORKDIR /app

# Copy the entire repo
COPY . .

# Install the project with dev dependencies
RUN pip install --no-cache-dir -e ".[dev]"

# Default: run the test suite
CMD ["pytest", "-q"]
