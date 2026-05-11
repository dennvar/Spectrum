"""
Static data for Spectrum cards.

Each entry is a (left_label, right_label) tuple representing the two
conceptual poles on the dial. The psychic sees the hidden target and
gives a clue; guessers use the card labels to calibrate.
"""

from __future__ import annotations

SPECTRUM_CARDS: list[tuple[str, str]] = [
    # Physical / sensory
    ("Hot", "Cold"),
    ("Loud", "Quiet"),
    ("Fast", "Slow"),
    ("Heavy", "Light"),
    ("Bright", "Dark"),
    ("Rough", "Smooth"),
    ("Big", "Small"),
    ("Tall", "Short"),
    ("Sharp", "Dull"),
    ("Sweet", "Bitter"),
    ("Wet", "Dry"),
    ("Soft", "Hard"),
    ("Full", "Empty"),
    ("Near", "Far"),
    ("Old", "New"),
    # Moral / evaluative
    ("Good", "Evil"),
    ("Safe", "Dangerous"),
    ("Honest", "Deceptive"),
    ("Brave", "Cowardly"),
    ("Generous", "Selfish"),
    ("Humble", "Arrogant"),
    ("Innocent", "Guilty"),
    ("Relaxing", "Stressful"),
    ("Satisfying", "Disappointing"),
    # Social / cultural
    ("Famous", "Unknown"),
    ("Expensive", "Cheap"),
    ("Formal", "Casual"),
    ("Mainstream", "Niche"),
    ("Urban", "Rural"),
    ("Serious", "Silly"),
    ("Complex", "Simple"),
    ("Realistic", "Fantastical"),
    ("Overrated", "Underrated"),
    ("Classy", "Tacky"),
    # Abstract / conceptual
    ("Logical", "Emotional"),
    ("Planned", "Spontaneous"),
    ("Timeless", "Trendy"),
    ("Natural", "Artificial"),
    ("Literal", "Metaphorical"),
    ("Predictable", "Surprising"),
    ("Risky", "Safe"),
    ("Ancient", "Futuristic"),
    ("Rare", "Common"),
    ("Chaotic", "Orderly"),
    ("Subtle", "Obvious"),
    ("Powerful", "Weak"),
]


def get_spectrum_cards() -> list[tuple[str, str]]:
    """Return a shallow copy of the full spectrum card list."""
    return list(SPECTRUM_CARDS)
