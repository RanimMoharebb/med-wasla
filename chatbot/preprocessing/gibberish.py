import re

import models
from preprocessing.spell_checker import spell
from memory.session import get_expected_answer


def _is_known_phrase_joined(word):
    """
    Catches casual, unspaced chitchat like "thankyou", "goodmorning", or
    "howareyou" that spellchecker can't correct as one word, but is
    really two or three known words joined together.
    """

    for i in range(2, len(word) - 1):

        left, right = word[:i], word[i:]

        if left in spell and right in spell:
            return True

        for j in range(2, len(right) - 1):

            if left in spell and right[:j] in spell and right[j:] in spell:
                return True

    return False


def _is_meaningless_word(word):
    """
    Returns True if a single token looks like keyboard mash rather than
    a real (or casually joined) word.
    """

    # One character
    if len(word) == 1:
        return True

    # Same character repeated (ee, eee, rrrr...)
    if len(set(word)) == 1:
        return True

    # A real dictionary word (or casual joined phrase like "thankyou")
    # is never gibberish, regardless of how few vowels it has (e.g.
    # "thanks", "rhythm") — skip the heuristics below.
    if word in spell or _is_known_phrase_joined(word):
        return False

    vowels = sum(
        c in "aeiou"
        for c in word
    )

    # kb, df, xpt, jgd, wxyz...
    if 2 <= len(word) <= 4 and vowels == 0:
        return True

    # qwrty, zxcvb...
    if len(word) >= 5 and vowels <= 1:
        return True

    # Not a dictionary word, and not even a fuzzy (edit-distance) match
    # to one — e.g. "fejubfr", "iksdujdsegde". Real words, including
    # medical terms and genuine typos, always have at least one
    # candidate. Restricted to len >= 5 so short real words with few
    # candidates (e.g. "ve") aren't misflagged.
    if len(word) >= 5 and not spell.candidates(word):
        return True

    return False


def is_gibberish(text, chat_id):
    """
    Returns True if the message appears to be gibberish.
    """

    text = text.strip().lower()

    if not text:
        return True

    # --------------------------------------------------
    # Numbers only
    # --------------------------------------------------
    if re.fullmatch(r"[0-9\s]+", text):

        # Allow numbers if the conversation is currently expecting a
        # numeric answer (age, pain scale, temperature). This is the
        # authoritative check: it comes from our own planner state,
        # not from guessing at the LLM's exact question wording.
        NUMERIC_EXPECTED_FIELDS = {"age", "pain_scale", "fever_temperature"}

        if get_expected_answer(chat_id) in NUMERIC_EXPECTED_FIELDS:
            return False

        # Fallback: no expected-field state available (or it wasn't
        # set) — infer from keywords in the bot's last message.
        history = models.chat_sessions.get(chat_id, [])

        if history:

            last_bot = None

            for turn in reversed(history):

                if turn["role"] == "assistant":
                    last_bot = turn["text"].lower()
                    break

            if last_bot:

                numeric_keywords = [
                    "how many",
                    "how long",
                    "how old",
                    "how much",
                    "your age",
                    "scale",
                    "1 to 10",
                    "rate",
                    "days",
                    "weeks",
                    "months",
                    "years",
                    "temperature",
                    "degrees"
                ]

                if any(
                    keyword in last_bot
                    for keyword in numeric_keywords
                ):
                    return False

        return True

    # --------------------------------------------------
    # Symbols only
    # --------------------------------------------------
    if re.fullmatch(r"[\W_]+", text):
        return True

    words = text.split()

    # --------------------------------------------------
    # Single meaningless token
    # --------------------------------------------------
    if len(words) == 1:
        return _is_meaningless_word(words[0])

    # --------------------------------------------------
    # Every token is individually meaningless — e.g. "x nv s" or a run
    # of keyboard-mash words. A real sentence only needs ONE genuine
    # word (a proper noun, medical term, etc.) to be exempted here.
    # --------------------------------------------------
    if all(_is_meaningless_word(word) for word in words):
        return True

    # --------------------------------------------------
    # Looks like normal text
    # --------------------------------------------------
    return False
