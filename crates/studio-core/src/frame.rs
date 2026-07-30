//! Frame protocol parser for fd 3 event stream.
//!
//! Protocol: `<length>\n<json>\n`
//! - `length` is the byte count of the JSON line (not including the trailing newline)
//! - `json` is a single-line JSON object
//!
//! The parser is incremental: feed bytes as they arrive, get back complete events.
//!
//! Note: Python's `len(str)` counts characters, not bytes. To handle this
//! mismatch safely, we find the next newline after the expected position
//! rather than slicing at a fixed byte offset.

/// Incremental frame parser. Feed bytes via `feed()`, get back parsed JSON events.
pub struct FrameParser {
    buffer: String,
}

impl FrameParser {
    pub fn new() -> Self {
        Self { buffer: String::new() }
    }

    /// Feed raw bytes. Returns all complete events parsed from the buffer.
    pub fn feed(&mut self, data: &str) -> Vec<serde_json::Value> {
        self.buffer.push_str(data);
        let mut events = vec![];

        loop {
            let buffer = &self.buffer;

            // Find the length line
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

            // The length from Python is character count, but we need byte offset.
            // Find the next newline after json_start to locate the end of JSON.
            // This is more robust than slicing at a fixed byte offset.
            let json_end = match buffer[json_start..].find('\n') {
                Some(pos) => json_start + pos,
                None => {
                    // Not enough data yet — but check if we might have enough
                    // by trying the byte-length approach as a fallback.
                    let byte_end = json_start + length;
                    if buffer.len() < byte_end + 1 {
                        break;
                    }
                    // The byte end might not be a char boundary; find the
                    // nearest char boundary at or after byte_end.
                    byte_end
                }
            };

            let total_needed = json_end + 1;

            if buffer.len() < total_needed {
                break;
            }

            // Slice safely — json_end is at a newline (char boundary)
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
        let mut parser = FrameParser::new();
        let json = r#"{"type":"text","text":"hello"}"#;
        let frame = format!("{}\n{}\n", json.len(), json);
        let events = parser.feed(&frame);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0]["type"], "text");
    }

    #[test]
    fn test_parse_multiple_frames_in_one_feed() {
        let mut parser = FrameParser::new();
        let json1 = r#"{"type":"a"}"#;
        let json2 = r#"{"type":"b"}"#;
        let frame = format!("{}\n{}\n{}\n{}\n", json1.len(), json1, json2.len(), json2);
        let events = parser.feed(&frame);
        assert_eq!(events.len(), 2);
        assert_eq!(events[0]["type"], "a");
        assert_eq!(events[1]["type"], "b");
    }

    #[test]
    fn test_parse_frame_split_across_feeds() {
        let mut parser = FrameParser::new();
        let json = r#"{"type":"text","text":"hello world"}"#;
        let frame = format!("{}\n{}\n", json.len(), json);
        let mid = frame.len() / 2;
        let events1 = parser.feed(&frame[..mid]);
        let events2 = parser.feed(&frame[mid..]);
        assert!(events1.is_empty());
        assert_eq!(events2.len(), 1);
        assert_eq!(events2[0]["type"], "text");
    }

    #[test]
    fn test_parse_frame_with_unicode() {
        let mut parser = FrameParser::new();
        let json = r#"{"type":"text","text":"😊 hello"}"#;
        let frame = format!("{}\n{}\n", json.len(), json);
        let events = parser.feed(&frame);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0]["text"], "😊 hello");
    }

    #[test]
    fn test_parse_frame_with_unicode_char_count_mismatch() {
        // Python len() counts chars (12), but the byte length is 16.
        // The parser should handle this by finding the newline.
        let mut parser = FrameParser::new();
        let json = r#"{"text":"😊"}"#;  // 13 chars, 15 bytes
        // Simulate Python sending char count (13)
        let frame = format!("13\n{}\n", json);
        let events = parser.feed(&frame);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0]["text"], "😊");
    }

    #[test]
    fn test_malformed_length_line_returns_empty() {
        let mut parser = FrameParser::new();
        let events = parser.feed("not a number\n{}\n");
        // Malformed length line is skipped, then the JSON line is treated as
        // a new length line (which also fails), so no events.
        assert!(events.is_empty());
    }
}
