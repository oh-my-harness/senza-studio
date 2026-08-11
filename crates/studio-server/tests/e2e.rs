//! E2E integration test: full HTTP flow through the studio-server.
//!
//! Tests the REST API surface end-to-end: project CRUD, examples listing,
//! creating a project from an example, and reading/writing files.

use std::sync::Arc;
use studio_server::state::AppState;
use studio_server::build_app;
use axum::body::Body;
use axum::http::{Request, StatusCode};
use tower::ServiceExt;

fn test_state() -> Arc<AppState> {
    let tmp = tempfile::tempdir().unwrap();
    let settings_path = tmp.path().join("settings.json");
    let projects_root = tmp.keep();
    Arc::new(AppState::new(projects_root, settings_path))
}

/// Percent-encode a project id for use in a request URI. Project ids are
/// now derived from free-form project names (e.g. "My Agent") rather than
/// always being a UUID, so test fixtures with spaces need real encoding —
/// matching what a correctly-encoding real HTTP client (e.g. the frontend's
/// `encodeURIComponent`) would send.
fn encode_id(id: &str) -> String {
    let mut out = String::new();
    for byte in id.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(byte as char);
            }
            _ => out.push_str(&format!("%{byte:02X}")),
        }
    }
    out
}

#[tokio::test]
async fn test_health() {
    let app = build_app(test_state());
    let res = app
        .oneshot(Request::builder().uri("/api/health").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
}

#[tokio::test]
async fn test_create_and_list_projects() {
    let state = test_state();
    let app = build_app(state);

    // Create a project
    let create_req = r#"{"name":"My Agent"}"#;
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/projects")
                .header("Content-Type", "application/json")
                .body(Body::from(create_req))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);

    let body = axum::body::to_bytes(res.into_body(), 1024 * 1024).await.unwrap();
    let project: serde_json::Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(project["name"], "My Agent");
    let project_id = project["id"].as_str().unwrap().to_string();

    // List projects
    let res = app
        .clone()
        .oneshot(Request::builder().uri("/api/projects").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let body = axum::body::to_bytes(res.into_body(), 1024 * 1024).await.unwrap();
    let projects: serde_json::Value = serde_json::from_slice(&body).unwrap();
    assert!(projects.as_array().unwrap().len() >= 1);

    // Get project details
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .uri(&format!("/api/projects/{}", encode_id(&project_id)))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);

    // Delete the project
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .method("DELETE")
                .uri(&format!("/api/projects/{}", encode_id(&project_id)))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::NO_CONTENT);

    // It's gone now
    let res = app
        .oneshot(
            Request::builder()
                .uri(&format!("/api/projects/{}", encode_id(&project_id)))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn test_list_examples() {
    let app = build_app(test_state());

    let res = app
        .oneshot(Request::builder().uri("/api/examples").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);

    let body = axum::body::to_bytes(res.into_body(), 1024 * 1024).await.unwrap();
    let examples: serde_json::Value = serde_json::from_slice(&body).unwrap();
    let arr = examples.as_array().unwrap();
    assert!(arr.len() >= 8, "expected at least 8 examples, got {}", arr.len());

    for ex in arr {
        assert!(ex["id"].is_string());
        assert!(ex["name"].is_string());
        assert!(ex["description"].is_string());
        assert!(ex["tags"].is_array());
    }
}

#[tokio::test]
async fn test_get_example_detail() {
    let app = build_app(test_state());

    let res = app
        .clone()
        .oneshot(Request::builder().uri("/api/examples/basic_chat").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);

    let body = axum::body::to_bytes(res.into_body(), 1024 * 1024).await.unwrap();
    let example: serde_json::Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(example["id"], "basic_chat");
    assert!(example["files"].is_array());
    assert!(example["files"].as_array().unwrap().len() >= 1);

    // Non-existent example
    let res = app
        .oneshot(Request::builder().uri("/api/examples/nonexistent").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn test_create_from_example() {
    let state = test_state();
    let app = build_app(state);

    let req = r#"{"example_id":"basic_chat","project_name":"My Chat Agent"}"#;
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/projects/from-example")
                .header("Content-Type", "application/json")
                .body(Body::from(req))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);

    let body = axum::body::to_bytes(res.into_body(), 1024 * 1024).await.unwrap();
    let result: serde_json::Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(result["files_copied"], 1);
    let project_id = result["project_id"].as_str().unwrap();

    // Verify the file was copied
    let res = app
        .oneshot(
            Request::builder()
                .uri(&format!("/api/projects/{}/files", encode_id(project_id)))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let body = axum::body::to_bytes(res.into_body(), 1024 * 1024).await.unwrap();
    let files: serde_json::Value = serde_json::from_slice(&body).unwrap();
    assert!(files.as_array().unwrap().contains(&serde_json::Value::String("main.py".into())));
}

#[tokio::test]
async fn test_write_and_read_file() {
    let state = test_state();
    let app = build_app(state);

    // Create a project first
    let create_req = r#"{"name":"File Test"}"#;
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/projects")
                .header("Content-Type", "application/json")
                .body(Body::from(create_req))
                .unwrap(),
        )
        .await
        .unwrap();
    let body = axum::body::to_bytes(res.into_body(), 1024 * 1024).await.unwrap();
    let project: serde_json::Value = serde_json::from_slice(&body).unwrap();
    let project_id = project["id"].as_str().unwrap();

    // Write a file
    let write_req = r#"{"content":"print('hello world')"}"#;
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .method("PUT")
                .uri(&format!("/api/projects/{}/files/test.py", encode_id(project_id)))
                .header("Content-Type", "application/json")
                .body(Body::from(write_req))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);

    // Read it back
    let res = app
        .oneshot(
            Request::builder()
                .uri(&format!("/api/projects/{}/files/test.py", encode_id(project_id)))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let body = axum::body::to_bytes(res.into_body(), 1024 * 1024).await.unwrap();
    let content = String::from_utf8(body.to_vec()).unwrap();
    assert!(content.contains("print('hello world')"));
}

#[tokio::test]
async fn test_get_spec_null_when_missing_and_404_for_bad_project() {
    let state = test_state();
    let app = build_app(state);

    let create_req = r#"{"name":"Spec Test"}"#;
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/projects")
                .header("Content-Type", "application/json")
                .body(Body::from(create_req))
                .unwrap(),
        )
        .await
        .unwrap();
    let body = axum::body::to_bytes(res.into_body(), 1024 * 1024).await.unwrap();
    let project: serde_json::Value = serde_json::from_slice(&body).unwrap();
    let project_id = project["id"].as_str().unwrap();

    // No spec has been generated yet — expect 200 with a null body, not an error.
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .uri(&format!("/api/projects/{}/spec", encode_id(project_id)))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let body = axum::body::to_bytes(res.into_body(), 1024 * 1024).await.unwrap();
    let spec: serde_json::Value = serde_json::from_slice(&body).unwrap();
    assert!(spec.is_null());

    // A nonexistent project should 404, not silently return null.
    let res = app
        .oneshot(
            Request::builder()
                .uri("/api/projects/does-not-exist/spec")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn test_get_pending_diff_null_when_missing_and_404_for_bad_project() {
    let state = test_state();
    let app = build_app(state);

    let create_req = r#"{"name":"Pending Diff Test"}"#;
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/projects")
                .header("Content-Type", "application/json")
                .body(Body::from(create_req))
                .unwrap(),
        )
        .await
        .unwrap();
    let body = axum::body::to_bytes(res.into_body(), 1024 * 1024).await.unwrap();
    let project: serde_json::Value = serde_json::from_slice(&body).unwrap();
    let project_id = project["id"].as_str().unwrap();

    // No diff has been emitted yet — expect 200 with a null body, not an error.
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .uri(&format!("/api/projects/{}/pending-diff", encode_id(project_id)))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let body = axum::body::to_bytes(res.into_body(), 1024 * 1024).await.unwrap();
    let diff: serde_json::Value = serde_json::from_slice(&body).unwrap();
    assert!(diff.is_null());

    // A nonexistent project should 404, not silently return null.
    let res = app
        .oneshot(
            Request::builder()
                .uri("/api/projects/does-not-exist/pending-diff")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn test_settings_get_and_save() {
    let state = test_state();
    let app = build_app(state);

    // Get default settings
    let res = app
        .clone()
        .oneshot(Request::builder().uri("/api/settings").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let body = axum::body::to_bytes(res.into_body(), 1024 * 1024).await.unwrap();
    let settings: serde_json::Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(settings["api_key"], "");
    assert_eq!(settings["model"], "gpt-4o");

    // Save settings
    let save_req = r#"{"api_key":"sk-test-123","base_url":"https://api.example.com"}"#;
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .method("PUT")
                .uri("/api/settings")
                .header("Content-Type", "application/json")
                .body(Body::from(save_req))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);

    // Verify saved
    let res = app
        .oneshot(Request::builder().uri("/api/settings").body(Body::empty()).unwrap())
        .await
        .unwrap();
    let body = axum::body::to_bytes(res.into_body(), 1024 * 1024).await.unwrap();
    let settings: serde_json::Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(settings["api_key"], "sk-test-123");
    assert_eq!(settings["base_url"], "https://api.example.com");
    assert_eq!(settings["model"], "gpt-4o"); // default preserved
}
