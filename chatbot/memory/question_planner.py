"""
question_planner.py

This file used to dictate an exact, universal field-by-field question
sequence (duration -> age -> pain_location -> pain_scale ->
pain_character) for every complaint, regardless of what it actually
was. That's been removed by design: the LLM now decides what to ask
and in what order, based on the specific complaint, using the
category guidance below as a menu of clinically relevant topics —
not a script.

What stays deterministic (non-negotiable, safety-critical):
- Red-flag / emergency detection. This is never left to model
  discretion.

What stays as lightweight bookkeeping (not questioning):
- Detecting which topic the model's own question was about, so a
  bare reply like "26" or "6" can still be correctly attributed to
  age/pain_scale/etc. This doesn't dictate what gets asked — it just
  helps correctly interpret the answer to whatever the model chose to
  ask.
"""

import re

from memory.memory import patient_state


# ==========================================================
# Emergency detection (deterministic — never LLM-driven)
# ==========================================================

def check_emergency(chat_id):
    """
    Returns True if emergency red-flag symptoms have been detected for
    this patient. This is the one thing in the medical flow that must
    always be guaranteed by code, never left to the model to notice or
    prioritize on its own.
    """

    if chat_id not in patient_state:
        return False

    return bool(patient_state[chat_id]["red_flags"])


# ==========================================================
# Symptom categories
# ==========================================================
# Broad, keyword-based buckets used only to pick a relevant menu of
# follow-up topics — not to enforce an order or a mandatory field.

_CATEGORY_KEYWORDS = {
    "headache_neuro": {
        "headache", "migraine", "dizziness", "numbness", "weakness",
        "confusion", "seizure", "vision changes", "blurred vision"
    },
    "respiratory": {
        "cough", "dry cough", "productive cough", "difficulty breathing",
        "shortness of breath", "wheezing", "sore throat", "congestion"
    },
    "gi": {
        "abdominal pain", "stomach pain", "nausea", "vomiting",
        "diarrhea", "constipation", "bloating", "heartburn"
    },
    "dermatological": {
        "rash", "itching", "skin", "swelling", "hives", "lesion"
    },
    "pain_general": {
        "chest pain", "back pain", "ear pain", "eye pain",
        "joint pain", "muscle pain"
    },
    "fever_infection": {
        "fever", "chills", "sweating"
    }
}

# Menus are a starting point of clinically relevant DIRECTIONS, not
# exact questions — the model picks what's still relevant, phrases it
# naturally, and can go beyond this list if something else is more
# clinically useful for what the patient has actually described.
_CATEGORY_GUIDANCE = {
    "headache_neuro": (
        "Relevant directions for this complaint (pick what's still "
        "useful, don't ask all of them): how long it's been going on; "
        "one side or both sides of the head; what it feels like "
        "(throbbing, dull, pressure, sharp); severity; any nausea, "
        "light/sound sensitivity, or visual changes (aura); what "
        "triggers or relieves it; neck stiffness; whether this is a "
        "new type of headache for them or a recurring pattern; age."
    ),
    "respiratory": (
        "Relevant directions for this complaint: how long it's been "
        "going on; whether the cough is dry or brings up "
        "phlegm/mucus (and what color, if so); fever; shortness of "
        "breath; chest pain; smoking history; any known exposure to "
        "illness; age."
    ),
    "gi": (
        "Relevant directions for this complaint: how long it's been "
        "going on; where exactly the pain/discomfort is; relation to "
        "eating; nausea or vomiting; bowel habit changes; fever; "
        "for a person who could be pregnant, whether that's a "
        "possibility; age."
    ),
    "dermatological": (
        "Relevant directions for this complaint: how long it's been "
        "present; exact location and whether it's spreading; itching "
        "vs. pain; any new soaps, products, foods, or medications "
        "recently; fever; age."
    ),
    "pain_general": (
        "Relevant directions for this complaint: how long it's been "
        "going on; exact location; severity; what it feels like "
        "(sharp, dull, burning, throbbing, cramping); what makes it "
        "better or worse; age."
    ),
    "fever_infection": (
        "Relevant directions for this complaint: how long the fever "
        "has been present; the actual temperature if measured; other "
        "symptoms alongside it (sore throat, rash, cough, body aches); "
        "age."
    ),
    "general": (
        "Relevant directions: how long this has been going on; "
        "severity or how much it's affecting daily life; anything "
        "that makes it better or worse; any other symptoms alongside "
        "it; age."
    )
}


def get_symptom_category(chat_id):
    """
    Returns a broad category label for the patient's current chief
    complaint, used only to select a relevant menu of follow-up
    directions — never to enforce a fixed order.
    """

    if chat_id not in patient_state:
        return "general"

    symptoms = patient_state[chat_id]["symptoms_present"]

    for category, keywords in _CATEGORY_KEYWORDS.items():
        if symptoms.intersection(keywords):
            return category

    return "general"


def get_symptom_exploration_guidance(chat_id):
    """
    Returns the relevance menu for the patient's current complaint
    category. This is guidance for the model's own judgment, not a
    checklist it must complete in order.
    """

    category = get_symptom_category(chat_id)
    return _CATEGORY_GUIDANCE.get(category, _CATEGORY_GUIDANCE["general"])


# ==========================================================
# Lightweight topic detection (bookkeeping, not questioning)
# ==========================================================
# Used only to figure out what a bare reply like "26" or "6" means,
# by checking what topic the model's OWN question (whatever it chose
# to ask) was actually about — this never dictates what gets asked.

_TOPIC_DETECTION_PATTERNS = {
    "age":
        re.compile(r"\bhow old\b|\byour age\b", re.IGNORECASE),

    "duration":
        re.compile(r"\bhow long\b|\bsince when\b|\bhow many (days|weeks|hours)\b", re.IGNORECASE),

    "pain_scale":
        re.compile(r"\bscale of\b.{0,10}\b10\b|\bhow severe\b|\bhow bad\b.{0,15}\bpain\b|\brate\b.{0,15}\bpain\b", re.IGNORECASE),

    "pain_location":
        re.compile(r"\bwhere\b.{0,20}\b(pain|hurt|located|it hurt)\b|\bwhich part\b", re.IGNORECASE),

    "pain_character":
        re.compile(r"\bdescribe the pain\b|\bsharp.{0,10}dull\b|\bwhat does (it|the pain) feel like\b", re.IGNORECASE),

    "fever_temperature":
        re.compile(r"\btemperature\b|\bhow high\b.{0,15}\bfever\b|\bmeasured\b.{0,15}\bfever\b", re.IGNORECASE),

    "smoking":
        re.compile(r"\bdo you smoke\b|\bsmoking\b", re.IGNORECASE),

    "pregnancy":
        re.compile(r"\bpregnan(t|cy)\b", re.IGNORECASE),
}


def detect_question_topic(answer_text):
    """
    Scans the model's own generated answer for which known topic (if
    any) it asked about, so the NEXT reply can be interpreted
    correctly (e.g. a bare "26" means age) — without the code ever
    having dictated what the model should ask.
    """

    if not answer_text:
        return None

    for field, pattern in _TOPIC_DETECTION_PATTERNS.items():
        if pattern.search(answer_text):
            return field

    return None
