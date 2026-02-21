"""Flashcard study page.

Shows flashcards for one or more lessons as a flip-card deck.
- Cards are shown one at a time (front first).
- Click "Reveal Answer" to flip.
- Navigate with Previous / Next.
- A progress bar tracks position in the deck.
- Shuffle toggle randomises the deck order.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import random
import streamlit as st
from tools.flashcard_tool import manage_flashcards

st.set_page_config(page_title="Flashcards", page_icon="🃏", layout="centered")

# ---------------------------------------------------------------------------
# Guard: must arrive here via session_state set by app.py
# ---------------------------------------------------------------------------
if "flashcard_lessons" not in st.session_state or not st.session_state["flashcard_lessons"]:
    st.warning("No flashcard session active. Please start a session from the home page.")
    if st.button("← Back to Setup"):
        st.switch_page("app.py")
    st.stop()

lessons: list[dict] = st.session_state["flashcard_lessons"]  # [{lesson_id, lesson_title, ...}]

# ---------------------------------------------------------------------------
# Load cards once per session (cache in session_state)
# ---------------------------------------------------------------------------
cache_key = "fc_deck_" + "_".join(str(l["lesson_id"]) for l in lessons)

if cache_key not in st.session_state:
    all_cards: list[dict] = []
    for lesson in lessons:
        result = manage_flashcards(action="list", lesson_id=lesson["lesson_id"])
        for card in result.get("flashcards", []):
            all_cards.append({**card, "lesson_title": lesson["lesson_title"]})
    random.shuffle(all_cards)
    st.session_state[cache_key] = all_cards
    st.session_state["fc_index"] = 0
    st.session_state["fc_revealed"] = False

deck: list[dict] = st.session_state[cache_key]

if not deck:
    st.info("No flashcards found for the selected lessons.")
    if st.button("← Back to Setup"):
        st.switch_page("app.py")
    st.stop()

# ---------------------------------------------------------------------------
# Header + controls
# ---------------------------------------------------------------------------
st.title("🃏 Flashcards")

col_info, col_shuffle = st.columns([3, 1])
with col_info:
    lesson_names = ", ".join(l["lesson_title"] for l in lessons)
    st.caption(f"Studying: {lesson_names}")

with col_shuffle:
    if st.button("🔀 Shuffle", use_container_width=True):
        shuffled = deck.copy()
        random.shuffle(shuffled)
        st.session_state[cache_key] = shuffled
        st.session_state["fc_index"] = 0
        st.session_state["fc_revealed"] = False
        st.rerun()

# ---------------------------------------------------------------------------
# Current card
# ---------------------------------------------------------------------------
idx: int = st.session_state["fc_index"]
revealed: bool = st.session_state["fc_revealed"]
card = deck[idx]

# Progress bar
progress_pct = (idx + 1) / len(deck)
st.progress(progress_pct, text=f"Card {idx + 1} of {len(deck)}")

# Card display
st.markdown("---")

card_container = st.container(border=True)
with card_container:
    # Lesson tag
    st.caption(f"📖 {card.get('lesson_title', '')}")

    # Tags
    tags = card.get("tags") or []
    if tags:
        st.caption("🏷️ " + "  ·  ".join(tags))

    st.markdown("### " + card["front"])

    if revealed:
        st.divider()
        st.markdown(card["back"])
    else:
        st.markdown("")
        if st.button("👁️ Reveal Answer", use_container_width=True, type="secondary"):
            st.session_state["fc_revealed"] = True
            st.rerun()

st.markdown("---")

# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------
prev_col, restart_col, next_col = st.columns([1, 1, 1])

with prev_col:
    if st.button("← Previous", use_container_width=True, disabled=idx == 0):
        st.session_state["fc_index"] = idx - 1
        st.session_state["fc_revealed"] = False
        st.rerun()

with restart_col:
    if st.button("↩ Restart Deck", use_container_width=True):
        st.session_state["fc_index"] = 0
        st.session_state["fc_revealed"] = False
        st.rerun()

with next_col:
    if idx < len(deck) - 1:
        if st.button("Next →", use_container_width=True, type="primary"):
            st.session_state["fc_index"] = idx + 1
            st.session_state["fc_revealed"] = False
            st.rerun()
    else:
        st.success("🎉 End of deck!")

st.divider()
if st.button("← Back to Setup", use_container_width=True):
    st.session_state.pop("flashcard_lessons", None)
    st.session_state.pop(cache_key, None)
    st.session_state["fc_index"] = 0
    st.session_state["fc_revealed"] = False
    st.switch_page("app.py")
