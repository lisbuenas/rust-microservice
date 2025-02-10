# Build stage
FROM rust:latest AS builder
WORKDIR /app
RUN rustup update stable && rustup default stable
COPY . .
RUN cargo build --release

# Runtime stage - Use Ubuntu as the base image
FROM ubuntu:latest
WORKDIR /app
COPY --from=builder /app/target/release/rust-microservice /app/
CMD ["/app/rust-microservice"]
