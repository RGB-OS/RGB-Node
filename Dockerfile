FROM python:3.11-slim

WORKDIR /app

# Install Rust and build tools
RUN apt-get update && apt-get install -y \
    curl build-essential git libssl-dev pkg-config libclang-dev cmake \
    && curl https://sh.rustup.rs -sSf | bash -s -- -y \
    && . $HOME/.cargo/env

# Clone rgb-lib and build Python bindings
RUN git clone https://github.com/RGB-Tools/rgb-lib.git /rgb-lib \
    && cd /rgb-lib/python \
    && /root/.cargo/bin/cargo build --release \
    && pip install .

# Copy your project files into container
COPY . .

# Install your API dependencies
RUN pip install fastapi uvicorn

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
