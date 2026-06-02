#!/usr/bin/env python3
import sys

with open('/app/app/services/brief_generator.py', 'r') as f:
    lines = f.readlines()

# Find line with "context_window = model_config.get"
for i, line in enumerate(lines):
    if 'context_window = model_config.get' in line:
        indent = line[:len(line) - len(line.lstrip())]
        # Insert after this line
        lines.insert(i + 1, f'{indent}max_tokens = model_config.get("max_completion_tokens", 16384)\n')
        break

# Also replace the hardcoded max_tokens=16384 with max_tokens variable
# Find line with "max_tokens=16384,"
for i, line in enumerate(lines):
    if 'max_tokens=16384,' in line:
        # Replace with max_tokens variable
        indent = line[:len(line) - len(line.lstrip())]
        lines[i] = f'{indent}max_tokens=max_tokens,\n'
        break

with open('/app/app/services/brief_generator.py', 'w') as f:
    f.writelines(lines)

print("Updated brief_generator to use model's max_completion_tokens")