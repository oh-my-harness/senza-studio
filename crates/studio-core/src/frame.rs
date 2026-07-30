//! Frame protocol parser for fd 3 event stream.
//!
//! Protocol: `<length>\n<json>\n`
//! - `length` is the byte count of the JSON line (not including the trailing newline)
//! - `json` is a single-line JSON object
//!
//! The parser is incremental: feed bytes as they arrive, get back complete events.

/// Incremental frame parser. Feed bytes via `feed()`, get back parsed JSON events.
pub struct FrameParser {
    buffer: String,
}

impl FrameParser {
    pub fn new() -> Self {
        Self {
            buffer: String::new(),
        }
    }

    /// Feed raw bytes. Returns all complete events parsed from the buffer.
    pub fn feed(&mut self, data: &str) -> Vec<serde_json::Value> {
        self.buffer.push_str(data);
        let mut events = vec![];

        loop {
            let buffer = &self.buffer;

            let newline_pos = match buffer.find('\n') {
                Some(pos) => pos,
                None => break,
            };

            let length_str = &buffer[..newline_pos];
            let length: usize = match length_str.trim().parse() {
                Ok(n) => n,
                Err(_) => {
                    self.buffer = buffer[newline_pos + 1..].to_string();
                    continue;
                }
            };

            let json_start = newline_pos + 1;
            let json_end = json_start + length;
            let total_needed = json_end + 1;

            if buffer.len() < total_needed {
                break;
            }

            let json_str = &buffer[json_start..json_end];
            match serde_json::from_str::<serde_json::Value>(json_str) {
                Ok(val) => events.push(val),
                Err(_) => {}
            }

            self.buffer = buffer[total_needed..].to_string();
        }

        events
    }
}

impl Default for FrameParser {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_single_frame() {
        let json = r#"{"type":"text_delta","text":"hello"}"#;
        let frame = format!("{}\n{}\n", json.len(), json);
        let mut parser = FrameParser::new();
        let events = parser.feed(&frame);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0]["type"], "text_delta");
        assert_eq!(events[0]["text"], "hello");
    }

    #[test]
    fn test_parse_multiple_frames_in_one_feed() {
        let json1 = r#"{"type":"text_delta","text":"a"}"#;
        let json2 = r#"{"type":"text_delta","text":"b"}"#;
        let data = format!("{}\n{}\n{}\n{}\n", json1.len(), json1, json2.len(), json2);
        let mut parser = FrameParser::new();
        let events = parser.feed(&data);
        assert_eq!(events.len(), 2);
        assert_eq!(events[0]["text"], "a");
        assert_eq!(events[1]["text"], "b");
    }

    #[test]
    fn test_parse_frame_split_across_feeds() {
        let json = r#"{"type":"settled"}"#;
        let frame = format!("{}\n{}\n", json.len(), json);
        let mut parser = FrameParser::new();

        let mid = frame.len() / 2;
        let events1 = parser.feed(&frame[..mid]);
        assert_eq!(events1.len(), 0);

        let events2 = parser.feed(&frame[mid..]);
        assert_eq!(events2.len(), 1);
        assert_eq!(events2[0]["type"], "settled");
    }

    #[test]
    fn test_parse_frame_with_unicode() {
        let json = r#"{"type":"text_delta","text":"你好世界"}"#;
        let frame = format!("{}\n{}\n", json.len(), json);
        let mut parser = FrameParser::new();
        let events = parser.feed(&frame);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0]["text"], "你好世界");
    }

    #[test]
    fn test_malformed_length_line_returns_empty() {
        let mut parser = FrameParser::new();
        let result = parser.feed("not_a_number\n");
        assert!(result.is_empty());
    }
}
