pub mod routes;
pub mod state;
pub mod ws;

use std::sync::Arc;
use axum::Router;
use state::AppState;

pub fn build_app(state: Arc<AppState>) -> Router {
    Router::new()
        .merge(routes::projects::router())
        .merge(routes::converse::router())
        .merge(routes::generate::router())
        .merge(routes::run::router())
        .merge(routes::examples::router())
        .merge(ws::converse::router())
        .merge(ws::run::router())
        .with_state(state)
}

pub async fn run_server(state: Arc<AppState>, addr: &str) -> anyhow::Result<()> {
    let app = build_app(state);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
