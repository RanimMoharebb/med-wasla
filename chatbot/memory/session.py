"""
Stores the logged-in user and conversation state for each chat session.
"""

# Logged-in user per session
_sessions = {}

# The name of the specialist most recently shown to the user
_last_specialist = {}
chat_symptoms = {}


# Which offers have already been fulfilled for a specialist
_fulfilled_offers = {}

# Conversation state (last detected intent + waiting for reply)
_conversation_state = {}

# Conversation phases
COLLECTING_SYMPTOMS = "COLLECTING_SYMPTOMS"
EMERGENCY = "EMERGENCY"
ENOUGH_INFORMATION = "ENOUGH_INFORMATION"

# ==========================================================
# User Session
# ==========================================================

def set_user(session_id: str, user_id: str):
    _sessions[session_id] = user_id


def get_user(session_id: str):
    return _sessions.get(session_id)


def remove_user(session_id: str):
    _sessions.pop(session_id, None)


# ==========================================================
# Last Specialist
# ==========================================================

def set_last_specialist_name(session_id: str, name: str):
    if name:
        _last_specialist[session_id] = name


def get_last_specialist_name(session_id: str):
    return _last_specialist.get(session_id)


# ==========================================================
# Fulfilled Offers
# ==========================================================

def mark_offer_fulfilled(session_id: str, specialist_name: str, offer_type: str):
    if not specialist_name:
        return

    _fulfilled_offers.setdefault(
        (session_id, specialist_name),
        set()
    ).add(offer_type)


def get_fulfilled_offers(session_id: str, specialist_name: str):
    return _fulfilled_offers.get(
        (session_id, specialist_name),
        set()
    )


# ==========================================================
# Conversation State
# ==========================================================

def set_conversation_state(chat_id: str, state: str):
    _conversation_state.setdefault(chat_id, {})
    _conversation_state[chat_id]["conversation_state"] = state


def get_conversation_state(chat_id: str):
    return (
        _conversation_state
        .get(chat_id, {})
        .get("conversation_state")
    )

def set_phase(chat_id: str, phase: str):
    _conversation_state.setdefault(chat_id, {})
    _conversation_state[chat_id]["phase"] = phase


def get_phase(chat_id: str):
    return (
        _conversation_state
        .get(chat_id, {})
        .get("phase")
    )

def set_last_question_type(chat_id: str, question_type: str):
    _conversation_state.setdefault(chat_id, {})
    _conversation_state[chat_id]["last_question_type"] = question_type


def get_last_question_type(chat_id: str):
    return (
        _conversation_state
        .get(chat_id, {})
        .get("last_question_type")
    )


def set_waiting_for_reply(chat_id: str, waiting: bool = True):
    _conversation_state.setdefault(chat_id, {})
    _conversation_state[chat_id]["waiting_for_reply"] = waiting


def is_waiting_for_reply(chat_id: str):
    return (
        _conversation_state
        .get(chat_id, {})
        .get("waiting_for_reply", False)
    )

def set_expected_answer(chat_id: str, field: str):
    _conversation_state.setdefault(chat_id, {})
    _conversation_state[chat_id]["expected_answer"] = field


def get_expected_answer(chat_id: str):
    return (
        _conversation_state
        .get(chat_id, {})
        .get("expected_answer")
    )

def clear_expected_answer(chat_id: str):
    if chat_id in _conversation_state:
        _conversation_state[chat_id].pop("expected_answer", None)


# ==========================================================
# Pending Login Offer
# ==========================================================
# Tracks whether the bot just offered to explain how to log in
# (shown to a logged-out user asking a database question), so a
# short affirmative reply ("yes please") can be answered with the
# actual login steps deterministically, without an LLM call.

def set_pending_login_offer(chat_id: str):
    _conversation_state.setdefault(chat_id, {})
    _conversation_state[chat_id]["pending_login_offer"] = True


def is_pending_login_offer(chat_id: str):
    return (
        _conversation_state
        .get(chat_id, {})
        .get("pending_login_offer", False)
    )


def clear_pending_login_offer(chat_id: str):
    if chat_id in _conversation_state:
        _conversation_state[chat_id].pop("pending_login_offer", None)

# ==========================================================
# Assistant Reply Detection
# ==========================================================

def assistant_is_waiting(answer: str):
    """
    Returns True if the assistant is asking the user
    for more information.
    """

    if not answer:
        return False

    answer = answer.lower().strip()

    question_phrases = [
        "can you",
        "could you",
        "would you",
        "do you",
        "have you",
        "are you",
        "is the",
        "is this",
        "what",
        "when",
        "where",
        "which",
        "who",
        "how",
        "tell me",
        "please describe",
        "please tell me"
    ]

    return (
        answer.endswith("?")
        or any(answer.startswith(phrase) for phrase in question_phrases)
    )