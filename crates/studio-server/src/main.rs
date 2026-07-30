use std::sync::Arc;
use studio_server::state::AppState;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt::init();

    let projects_root = std::env::var("SENZA_STUDIO_PROJECTS_DIR")
        .unwrap_or_else(|_| "./projects".into());
    let settings_path = std::env::var("SENZA_STUDIO_SETTINGS_PATH")
        .unwrap_or_else(|_| "./settings.json".into());
    let addr = std::env::var("SENZA_STUDIO_ADDR")
        .unwrap_or_else(|_| "0.0.0.0:3000".into());

    std::fs::create_dir_all(&projects_root)?;

    let state = Arc::new(AppState::new(
        projects_root.into(),
        settings_path.into(),
    ));

    eprintln!("Senza Studio server listening on {addr}");
    studio_server::run_server(state, &addr).await
}
