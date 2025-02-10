use warp::Filter;
use serde::Serialize;
use tracing::{info, Level};
use tracing_subscriber;

#[derive(Serialize)]
struct Message {
    message: String,
}

#[tokio::main]
async fn main() {
    // Initialize logging
    tracing_subscriber::fmt()
        .with_max_level(Level::INFO)
        .init();

    info!("Rust Microservice is starting...");

    let hello = warp::path("hello")
        .map(|| warp::reply::json(&Message { message: "Hello, world!".to_string() }));

    let root = warp::path::end()
        .map(|| warp::reply::json(&Message { message: "Welcome to the Rust Microservice!".to_string() }));

    let routes = warp::any().and(hello.or(root));

    info!("Server is running on http://0.0.0.0:8080");

    warp::serve(routes)
        .run(([0, 0, 0, 0], 8080))
        .await;
}
