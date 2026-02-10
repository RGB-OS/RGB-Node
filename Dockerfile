# rgb_lib wheel is cp311 + manylinux x86_64; use 3.11 and amd64 for compatibility
FROM --platform=linux/amd64 python:3.11-slim

WORKDIR /app

COPY requirements.txt .
COPY source/rgb_lib-0.3.0b10-cp311-cp311-manylinux_2_35_x86_64.whl ./source/
COPY . .

RUN pip install --no-cache-dir source/rgb_lib-0.3.0b10-cp311-cp311-manylinux_2_35_x86_64.whl && \
    pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

