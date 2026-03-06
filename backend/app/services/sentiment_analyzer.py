"""Simple rule-based sentiment analyzer for OSINT content."""
import re
from typing import Tuple

# Negative indicators (conflict, threat, danger)
NEGATIVE_WORDS = frozenset([
    'attack', 'strike', 'bomb', 'missile', 'killed', 'dead', 'death', 'destroyed',
    'explosion', 'shelling', 'casualties', 'wounded', 'injured', 'crisis', 'threat',
    'war', 'conflict', 'invasion', 'occupation', 'siege', 'ambush', 'raid',
    'terrorism', 'terrorist', 'extremist', 'insurgent', 'militant',
    'sanctions', 'embargo', 'collapse', 'crash', 'violation', 'breach',
    'arrested', 'detained', 'abducted', 'kidnapped', 'hostage',
    'evacuation', 'displaced', 'refugees', 'humanitarian',
    'escalation', 'tension', 'provocation', 'retaliation',
    'nuclear', 'chemical', 'biological', 'weapon', 'ammunition',
])

# Positive indicators (peace, stability, progress)
POSITIVE_WORDS = frozenset([
    'peace', 'ceasefire', 'agreement', 'treaty', 'negotiation', 'dialogue',
    'aid', 'assistance', 'relief', 'recovery', 'rebuild', 'reconstruction',
    'liberated', 'freed', 'rescued', 'saved', 'protected',
    'cooperation', 'alliance', 'partnership', 'diplomacy', 'diplomatic',
    'growth', 'development', 'progress', 'improvement', 'stability',
    'election', 'democratic', 'reform', 'investment',
])


def analyze_sentiment(text: str) -> Tuple[float, str]:
    """Analyze text sentiment. Returns (score, label).

    Score: -1.0 (very negative) to +1.0 (very positive). 0 = neutral.
    Label: 'negative', 'neutral', 'positive'
    """
    if not text:
        return 0.0, 'neutral'

    words = set(re.findall(r'[a-z]+', text.lower()))
    neg_count = len(words & NEGATIVE_WORDS)
    pos_count = len(words & POSITIVE_WORDS)
    total = neg_count + pos_count

    if total == 0:
        return 0.0, 'neutral'

    score = (pos_count - neg_count) / total  # -1 to +1

    if score < -0.2:
        label = 'negative'
    elif score > 0.2:
        label = 'positive'
    else:
        label = 'neutral'

    return round(score, 3), label
