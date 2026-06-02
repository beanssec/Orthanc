#!/usr/bin/env python3
import re

with open('/app/app/services/ai_models.py', 'r') as f:
    lines = f.readlines()

# Map model ID to max_completion_tokens
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
    # live models will be handled separately
}

new_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    new_lines.append(line)
    # Look for "id": "..."
    match = re.search(r'"id"\s*:\s*"([^"]+)"', line)
    if match:
        model_id = match.group(1)
        if model_id in defaults:
            # Find the line with "key_field": "api_key",
            # It's somewhere after this line, before the next '}' at same indentation
            # We'll search forward
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith('}'):
                if '"key_field":' in lines[j]:
                    indent = lines[j][:len(lines[j]) - len(lines[j].lstrip())]
                    new_lines.append(f'{indent}"max_completion_tokens": {defaults[model_id]},\n')
                    break
                j += 1
    i += 1

with open('/app/app/services/ai_models.py', 'w') as f:
    f.writelines(new_lines)

print("Updated static AI_MODELS with max_completion_tokens")