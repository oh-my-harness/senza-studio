pub mod routes;
pub mod settings_store;
pub mod state;
pub mod ws;

use std::sync::Arc;
use axum::Router;
use state::AppState;

pub fn build_app(state: Arc<AppState>) -> Router {
    let static_dir = std::env::var("SENZA_STUDIO_FRONTEND_DIR")
        .unwrap_or_else(|_| "./frontend/dist".into());

    let api_routes = Router::new()
        .merge(routes::projects::router())
        .merge(routes::converse::router())
        .merge(routes::generate::router())
        .merge(routes::run::router())
        .merge(routes::examples::router())
        .merge(routes::settings::router())
        .merge(ws::converse::router())
        .merge(ws::run::router())
        .with_state(state);

    Router::new()
        .route("/api/health", axum::routing::get(|| async { "ok" }))
        .merge(api_routes)
        .fallback_service(tower_http::services::ServeDir::new(static_dir))
}

pub async fn run_server(state: Arc<AppState>, addr: &str) -> anyhow::Result<()> {
    let app = build_app(state);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
