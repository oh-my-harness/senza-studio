//! StudioTool helper: reduces Tool trait implementation boilerplate.
//!
//! Each StudioTool holds:
//! - name, description, JSON Schema (static data)
//! - a handler function that receives args + ToolContext
//!
//! The handler uses HRTB (higher-ranked trait bounds) to work with any
//! lifetime of ToolContext.

use std::sync::Arc;
use futures::future::BoxFuture;
use llm_harness_types::{Tool, ToolContext, ToolFailure, ToolResult};
use serde_json::Value;

/// Context passed to a StudioTool handler.
pub struct ToolInvocation<'a> {
    pub args: Value,
    pub ctx: &'a ToolContext,
}

impl<'a> ToolInvocation<'a> {
    pub fn new(args: Value, ctx: &'a ToolContext) -> Self {
        Self { args, ctx }
    }
}

/// A tool handler function type using HRTB.
pub type ToolHandler = Box<
    dyn for<'a> Fn(ToolInvocation<'a>) -> BoxFuture<'a, Result<ToolResult, ToolFailure>>
        + Send
        + Sync,
>;

/// A tool built from a name, description, schema, and async handler.
pub struct StudioTool {
    name: String,
    description: String,
    schema: Value,
    handler: ToolHandler,
}

impl StudioTool {
    pub fn new(
        name: impl Into<String>,
        description: impl Into<String>,
        schema: Value,
        handler: ToolHandler,
    ) -> Self {
        Self {
            name: name.into(),
            description: description.into(),
            schema,
            handler,
        }
    }
}

impl Tool for StudioTool {
    fn name(&self) -> &str {
        &self.name
    }

    fn description(&self) -> &str {
        &self.description
    }

    fn parameters_schema(&self) -> &Value {
        &self.schema
    }

    fn execute<'a>(
        &'a self,
        args: Value,
        ctx: &'a ToolContext,
    ) -> BoxFuture<'a, Result<ToolResult, ToolFailure>> {
        let invocation = ToolInvocation::new(args, ctx);
        (self.handler)(invocation)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use llm_harness_types::DataBlock;

    #[test]
    fn test_studio_tool_name_and_description() {
        let schema = serde_json::json!({"type": "object"});
        let tool = StudioTool::new(
            "test_tool",
            "A test tool",
            schema.clone(),
            Box::new(|_invocation| {
                Box::pin(async move {
                    Ok(ToolResult::full(
                        vec![DataBlock::text("ok")],
                        serde_json::json!({}),
                        false,
                    ))
                })
            }),
        );

        assert_eq!(tool.name(), "test_tool");
        assert_eq!(tool.description(), "A test tool");
        assert_eq!(tool.parameters_schema(), &schema);
    }

    #[test]
    fn test_studio_tool_multiple_instances() {
        let tool1 = StudioTool::new(
            "tool1",
            "First tool",
            serde_json::json!({"type": "object"}),
            Box::new(|_invocation| {
                Box::pin(async move {
                    Ok(ToolResult::full(
                        vec![DataBlock::text("1")],
                        serde_json::json!({}),
                        false,
                    ))
                })
            }),
        );

        let tool2 = StudioTool::new(
            "tool2",
            "Second tool",
            serde_json::json!({"type": "object"}),
            Box::new(|_invocation| {
                Box::pin(async move {
                    Ok(ToolResult::full(
                        vec![DataBlock::text("2")],
                        serde_json::json!({}),
                        false,
                    ))
                })
            }),
        );

        assert_eq!(tool1.name(), "tool1");
        assert_eq!(tool2.name(), "tool2");
    }
}
