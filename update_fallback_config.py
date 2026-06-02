#!/usr/bin/env python3
import re

with open('/app/app/services/ai_models.py', 'r') as f:
    lines = f.readlines()

# Find make_fallback_model_config function
in_func = False
for i, line in enumerate(lines):
    if line.strip().startswith('def make_fallback_model_config'):
        in_func = True
    if in_func and line.strip().startswith('return {'):
        # This is the default return dict
        # Find the closing brace
        for j in range(i, len(lines)):
            if lines[j].strip() == '}':
                # Insert before this line
                indent = lines[j][:len(lines[j]) - len(lines[j].lstrip())]
                lines.insert(j, f'{indent}"max_completion_tokens": 16384,\n')
                break
        # Also need to handle cached case: we need to add max_completion_tokens to cached copy
        # Find earlier return {**cached}
        for k in range(i, j):
            if 'return {**cached}' in lines[k]:
                # We'll replace with something that adds missing key
                # Actually cached already has max_completion_tokens from fetch_live_openrouter_models
                # So no change needed.
                pass
        break

with open('/app/app/services/ai_models.py', 'w') as f:
    f.writelines(lines)

print("Updated make_fallback_model_config with max_completion_tokens")