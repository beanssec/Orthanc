#!/usr/bin/env python3
import json
import re
from pathlib import Path

file_path = Path("/mnt/data/projects/overwatch/backend/app/services/ai_models.py")
content = file_path.read_text()

# Find AI_MODELS = [
pattern = r'(AI_MODELS\s*=\s*\[)(.*?)(\n\])'
match = re.search(pattern, content, re.DOTALL)
if not match:
    print("AI_MODELS not found")
    exit(1)

models_block = match.group(2)
# Split by entries (each entry starts with { and ends with },)
# This is hacky but works for this simple structure
entries = []
start = 0
depth = 0
for i, ch in enumerate(models_block):
    if ch == '{':
        if depth == 0:
            start = i
        depth += 1
    elif ch == '}':
        depth -= 1
        if depth == 0:
            entries.append(models_block[start:i+1])

print(f"Found {len(entries)} model entries")

# Define default max_completion_tokens per model ID
defaults = {
    "grok-3-mini": 8192,
    "grok-3": 8192,
    "anthropic/claude-sonnet-4": 4096,
    "anthropic/claude-3.5-haiku": 4096,
    "openai/gpt-4o": 4096,
    "openai/gpt-4o-mini": 4096,
    "google/gemini-2.5-flash": 8192,
    "mistralai/mistral-large-2411": 4096,
    "meta-llama/llama-3.3-70b-instruct": 4096,
    "minimax/minimax-m2.7": 16384,
    # For any other models, default to 4096
}

new_entries = []
for entry in entries:
    # Parse as JSON? Not exactly because trailing commas etc. Let's just find "id": "value"
    id_match = re.search(r'"id"\s*:\s*"([^"]+)"', entry)
    if not id_match:
        new_entries.append(entry)
        continue
    model_id = id_match.group(1)
    max_tokens = defaults.get(model_id, 4096)
    # Insert after "key_field": "api_key", (or before the closing brace)
    # Find last line before closing brace
    lines = entry.split('\n')
    new_lines = []
    for line in lines:
        new_lines.append(line)
        if line.strip().startswith('"key_field":'):
            # Add max_completion_tokens after this line
            indent = line[:len(line) - len(line.lstrip())]
            new_lines.append(f'{indent}"max_completion_tokens": {max_tokens},')
    new_entry = '\n'.join(new_lines)
    new_entries.append(new_entry)

new_models_block = ',\n'.join(new_entries)
new_content = content[:match.start(2)] + new_models_block + content[match.end(2):]

# Write back
file_path.write_text(new_content)
print("Updated AI_MODELS with max_completion_tokens")