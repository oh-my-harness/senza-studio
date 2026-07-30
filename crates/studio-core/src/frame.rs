//! Frame protocol parser for fd 3 event stream.
//!
//! Protocol: `<length>\n<json>\n`
//! - `length` is the character count of the JSON line (from Python `len()`)
//! - `json` is a single-line JSON object (newlines escaped by `json.dumps`)
//!
//! The parser is **newline-delimited**: it ignores the length field and finds
//! the next `\n` to locate JSON boundaries. This avoids the char-count vs
//! byte-offset mismatch that occurs with multibyte UTF-8 characters.

/// Incremental frame parser. Feed bytes via `feed()`, get back parsed JSON events.
pub struct FrameParser {
    buffer: String,
}

impl FrameParser {
    pub fn new() -> Self {
        Self { buffer: String::new() }
    }

    /// Feed raw data. Returns all complete events parsed from the buffer.
    pub fn feed(&mut self, data: &str) -> Vec<serde_json::Value> {
        self.buffer.push_str(data);
        let mut events = vec![];

        loop {
            let buffer = &self.buffer;

            // Find the length line (first newline)
            let newline_pos = match buffer.find('\n') {
                Some(pos) => pos,
                None => break,
            };

            let length_str = &buffer[..newline_pos];
            let json_start = newline_pos + 1;

            // Validate length line is a number; if not, skip it as garbage
            let _length: usize = match length_str.trim().parse() {
                Ok(n) => n,
                Err(_) => {
                    self.buffer = buffer[json_start..].to_string();
                    continue;
                }
            };

            // Find the JSON line ending (next newline after json_start)
            let json_end = match buffer[json_start..].find('\n') {
                Some(pos) => json_start + pos,
                None => break, // Not enough data yet — wait for more
            };

            let json_str = &buffer[json_start..json_end];
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(json_str) {
                events.push(val);
            }

            self.buffer = buffer[json_end + 1..].to_string();
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
        // Python len() counts chars (13), but the byte length is 15.
        // The parser ignores the length and uses newlines — works either way.
        let mut parser = FrameParser::new();
        let json = r#"{"text":"😊"}"#; // 13 chars, 15 bytes
        let frame = format!("13\n{}\n", json);
        let events = parser.feed(&frame);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0]["text"], "😊");
    }

    #[test]
    fn test_parse_many_frames_with_unicode() {
        let mut parser = FrameParser::new();
        let json = r#"{"type":"text_delta","text":"Hi there! 😊"}"#;
        let mut frame = String::new();
        for _ in 0..60 {
            frame.push_str(&format!("{}\n{}\n", json.len(), json));
        }
        let events = parser.feed(&frame);
        assert_eq!(events.len(), 60);
    }

    #[test]
    fn test_malformed_length_line_returns_empty() {
        let mut parser = FrameParser::new();
        let events = parser.feed("not a number\n{}\n");
        assert!(events.is_empty());
    }
}
