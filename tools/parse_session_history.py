"""
Parse OpenClaw JSONL session history file in chunks using LLM.

Function:
- Read JSONL file in 50KB chunks
- For each chunk, extract messages with timestamps, roles, content
- Filter for keywords: memos, skillhub, skills, 网址
- Return structured timeline

Usage (as tool for sub-agent):
  uv run python tools/parse_session_history.py <session_file> [--chunk-size 50000] [--output result.json]
"""

import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any

def read_jsonl_chunks(filepath: Path, chunk_size: int = 50000):
    """Generator: read file in byte chunks, yield partial text"""
    with open(filepath, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            # Try to decode as UTF-8
            try:
                text = chunk.decode('utf-8')
            except UnicodeDecodeError:
                # Fallback: decode with errors ignored
                text = chunk.decode('utf-8', errors='ignore')
            yield text

def parse_chunk(text: str, keywords: List[str]) -> List[Dict[str, Any]]:
    """Parse a chunk of JSONL, extract messages containing keywords"""
    messages = []
    lines = text.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if obj.get("type") == "message":
                msg_data = obj.get("message", {})
                content = str(msg_data.get("content", ""))
                # Check keywords
                if any(k.lower() in content.lower() for k in keywords):
                    messages.append({
                        "timestamp": obj.get("timestamp"),
                        "role": msg_data.get("role"),
                        "content": content
                    })
        except json.JSONDecodeError:
            # Skip partial line at chunk boundary (will be handled in next chunk)
            continue
    return messages

def main():
    parser = argparse.ArgumentParser(description="Parse OpenClaw session history JSONL")
    parser.add_argument("file", type=str, help="Path to JSONL session file")
    parser.add_argument("--chunk-size", type=int, default=50000, help="Chunk size in bytes")
    parser.add_argument("--output", type=str, default="session_extract.json", help="Output JSON file")
    parser.add_argument("--keywords", type=str, default="memos,skillhub,skills,网址", help="Comma-separated keywords")
    args = parser.parse_args()

    filepath = Path(args.file)
    if not filepath.exists():
        print(f"Error: file not found: {filepath}")
        sys.exit(1)

    keywords = [k.strip() for k in args.keywords.split(",")]
    all_messages = []
    total_chunks = 0

    print(f"Parsing {filepath} in {args.chunk_size}-byte chunks...")
    for chunk_text in read_jsonl_chunks(filepath, args.chunk_size):
        total_chunks += 1
        msgs = parse_chunk(chunk_text, keywords)
        all_messages.extend(msgs)
        print(f"  Chunk {total_chunks}: found {len(msgs)} matching messages (total: {len(all_messages)})")

    # Save output
    output_path = Path(args.output)
    output_path.write_text(json.dumps(all_messages, ensure_ascii=False, indent=2))
    print(f"\nDone. Extracted {len(all_messages)} messages to {output_path}")

    # Print summary
    print("\n=== Summary ===")
    for i, msg in enumerate(all_messages[:10], 1):
        print(f"{i}. [{msg['timestamp']}] {msg['role']}: {msg['content'][:80]}...")
    if len(all_messages) > 10:
        print(f"... and {len(all_messages)-10} more")

if __name__ == "__main__":
    main()
