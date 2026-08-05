from spellchecker import SpellChecker


# create a single instance (used across project)
spell = SpellChecker()

# Domain-specific words/abbreviations that must never be "corrected" —
# pyspellchecker doesn't know them and would otherwise mangle them
# (observed: "drs" -> "dry", "dr." -> "dry"), corrupting queries before
# they ever reach classification or specialist-name matching.
_DOMAIN_WHITELIST = {
    "drs", "docs", "dr", "specialist", "specialists",
    "med-wasla", "medwasla", "waslabot"
}


def clean_query(user_query):
    """
    Cleans and corrects spelling in user input.
    """

    original_words = user_query.strip().split()
    query = user_query.strip().lower()

    try:
        words = query.split()

        unknown = spell.unknown(words)

        corrected = []

        for i, word in enumerate(words):

            # handle shortcut "iam"
            if word == "iam":
                corrected.extend(["i", "am"])
                continue

            original_word = original_words[i] if i < len(original_words) else word

            # Never "correct" a word that was capitalized in the
            # original message — almost always a proper noun (a
            # patient's or doctor's name, a place, etc.), and
            # dictionary-based correction has no way to know real
            # names, so it just mangles them (e.g. "Khaled" -> "whaled").
            is_likely_proper_noun = original_word[:1].isupper()

            # Never "correct" short tokens or ones containing
            # punctuation — these are almost always abbreviations
            # ("dr.", "drs", "st.") rather than typos, and short-word
            # correction is especially unreliable and high-risk.
            looks_like_abbreviation = (
                len(word) <= 3 or not word.isalpha()
            )

            if (
                word in unknown
                and word not in _DOMAIN_WHITELIST
                and not is_likely_proper_noun
                and not looks_like_abbreviation
            ):
                fixed = spell.correction(word)
                corrected.append(fixed if fixed else word)
            else:
                corrected.append(word)

        return " ".join(corrected)

    except Exception as e:

        print(f"⚠️ Spell correction skipped: {e}")

        return query