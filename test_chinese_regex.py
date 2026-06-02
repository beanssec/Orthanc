import sys
sys.path.insert(0, '/app')
import re
# The updated regex from translator.py
CHINESE_RE = re.compile(r"[\u4E00-\u9FFF\u3400-\u4DBF\U00020000-\U0002A6DF]")
# Test with English text
english = "Just finished mapping the new region! #GISAdventures"
matches = CHINESE_RE.findall(english)
print('English matches:', matches)
print('Count:', len(matches))
# Test with Chinese text
chinese = "你好世界"
matches2 = CHINESE_RE.findall(chinese)
print('Chinese matches:', matches2)
print('Count:', len(matches2))
# Test with mixed
mixed = "Hello 你好 World"
matches3 = CHINESE_RE.findall(mixed)
print('Mixed matches:', matches3)
print('Count:', len(matches3))
# Print Unicode code points of matched characters
for m in matches:
    print(f'{m} U+{ord(m):04X}')
for m in matches2:
    print(f'{m} U+{ord(m):04X}')
for m in matches3:
    print(f'{m} U+{ord(m):04X}')