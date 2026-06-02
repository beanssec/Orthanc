#!/usr/bin/env python3
import re

with open('/app/app/services/ai_models.py', 'r') as f:
    lines = f.readlines()

# Find the fetch_live_openrouter_models function
in_func = False
in_loop = False
for i, line in enumerate(lines):
    if line.strip().startswith('async def fetch_live_openrouter_models'):
        in_func = True
    if in_func and 'for m in data.get("data", []):' in line:
        in_loop = True
    if in_loop and line.strip().startswith('results.append({'):
        # Find the line with "context_window": ctx,
        for j in range(i, len(lines)):
            if '"context_window": ctx,' in lines[j]:
                indent = lines[j][:len(lines[j]) - len(lines[j].lstrip())]
                # Insert after this line
                lines.insert(j + 1, f'{indent}"max_completion_tokens": m.get("max_completion_tokens") or min(16384, ctx // 4),\n')
                break
        # Only need to do once per loop, but there's only one append
        break

with open('/app/app/services/ai_models.py', 'w') as f:
    f.writelines(lines)

print("Updated fetch_live_openrouter_models with max_completion_tokens")