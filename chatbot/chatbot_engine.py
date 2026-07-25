# -*- coding: utf-8 -*-

from cmath import phase
import re
from datetime import datetime, timezone

from typer import prompt

from core.router import keyword_route

from models import chat_sessions

from core.loader import initialize_model
from core.classifier import classify_question

from memory.question_planner import (
    get_next_missing_information,
    get_followup_guidance,
    get_followup_question
)

from preprocessing.gibberish import is_gibberish
from preprocessing.spell_checker import clean_query
from preprocessing.sensitive_guard import is_sensitive_request, REFUSAL_MESSAGE

from preprocessing.write_action_guard import (
    get_requested_action,
    get_requested_info,
    build_action_guard_message,
    is_unrecognized_offer_confirmation,
    GENERIC_NO_ACTION_MESSAGE,
    _AFFIRMATIVE_RE
)

from memory.memory import (
    add_message,
    get_history,
    get_symptom_summary,
    has_explained_causes,
    mark_causes_explained,
    # is_patient_ready, will use later
    # update_patient_entities,
    # set_expected_answer
)

from memory.chitchat import get_chitchat_response

from memory.session import (
    get_user,
    set_expected_answer,
    clear_expected_answer,
    set_pending_login_offer,
    is_pending_login_offer,
    clear_pending_login_offer,
    set_last_specialist_name,
    get_last_specialist_name,
    mark_offer_fulfilled,
    get_fulfilled_offers,
    set_last_question_type,
    get_last_question_type,
    set_waiting_for_reply,
    assistant_is_waiting,
    set_conversation_state,
    get_conversation_state,
    set_phase,
    get_phase,
    COLLECTING_SYMPTOMS,
    EMERGENCY,
    ENOUGH_INFORMATION
)

from core.retrieval import retrieve_documents
from core.prompt_builder import (
    build_combined_prompt,
    build_chitchat_prompt,
    build_database_prompt
)
from core.ollama_client import generate_response

from database.services.chatbot_service import get_user_context
from database.services.database_classifier import extract_specialization
from database.services.database_formatter import _format_slots, _safe_date
from database.collections.specialist_queries import (
    get_specialist_by_name,
    get_specialists_by_specialization,
    get_approved_specialists
)
from database.collections.appointment_queries import get_patient_upcoming_appointments

from config import SIMILARITY_THRESHOLD, ENABLE_DATABASE


# Defense-in-depth: the CLINICAL PLANNER block in build_combined_prompt
# is internal metadata the model should never echo (see prompt_builder.py).
# Defense-in-depth: the CLINICAL PLANNER block in build_combined_prompt
# is internal metadata the model should never echo (see prompt_builder.py).
# The prompt instructs it not to, but a local LLM can still slip
# occasionally — this strips any leaked "Planner Decision" style block,
# or other meta-commentary about the internal question-planning
# mechanism, out of the final answer before it ever reaches the user.
_PLANNER_LEAK_PATTERNS = [
    re.compile(
        r"planner\s*decision.*?required\s*follow-?up\s*question\s*:?\s*.*?(?:\n\s*\n|\Z)",
        re.IGNORECASE | re.DOTALL
    ),
    # e.g. "The system will automatically append the next required
    # field: 'age'" (with or without the quoted field name after it)
    re.compile(
        r"(?:the\s+)?system\s+(?:will|automatically)\s+(?:automatically\s+)?append[^\n.]*(?:required\s+field[^\n.]*)?[.:]?\s*(?:[\"'][a-z_]+[\"'])?\.?",
        re.IGNORECASE
    ),
    # e.g. "Please note that I'll ask only ONE additional clinically
    # relevant question if necessary, but for now, let's focus on..."
    re.compile(
        r"please note that i'?ll ask[^\n.]*\.", re.IGNORECASE
    ),
    re.compile(
        r"next\s+required\s+field\s*:?\s*(?:[\"'][a-z_]+[\"'])?\.?", re.IGNORECASE
    ),
    # e.g. "That's not a medical question. However, ..." — self-
    # contradictory hallucination, since this code path only runs when
    # the message WAS already classified as medical/platform-related.
    re.compile(
        r"that'?s?\s+not\s+(?:a\s+)?medical\s+question\.?\s*", re.IGNORECASE
    ),
    re.compile(
        r"this\s+(?:is|isn'?t|is\s+not)\s+(?:a\s+)?medical\s+question\.?\s*", re.IGNORECASE
    ),
    # e.g. "Here is a possible response from WaslaBot:" — meta-
    # commentary narrating the model's own reply instead of just
    # giving it.
    re.compile(
        r"here'?s?\s+(?:is\s+)?a\s+possible\s+response\s+from\s+wasla\s*bot\s*:?\s*", re.IGNORECASE
    ),
]


def _strip_leaked_planner_block(answer):
    if not answer:
        return answer

    cleaned = answer

    for pattern in _PLANNER_LEAK_PATTERNS:
        cleaned = pattern.sub("", cleaned)

    # Collapse leftover blank lines created by the removals above
    cleaned = re.sub(r"\n\s*\n\s*\n+", "\n\n", cleaned)

    return cleaned.strip()


def _strip_trailing_questions(answer):
    """
    Removes any trailing sentence(s) that end in '?' from the model's
    answer. Used right before appending the guaranteed follow-up
    question, so that even if the model disobeys the "don't ask a
    question yourself" instruction, the patient doesn't see two
    competing questions (e.g. "How old are you? Could you tell me
    your age?").
    """
    if not answer:
        return answer

    # Split into sentences on ., !, ? followed by whitespace, keeping
    # the delimiter attached to each sentence.
    sentences = re.split(r"(?<=[.!?])\s+", answer.strip())

    while sentences and sentences[-1].strip().endswith("?"):
        sentences.pop()

    return " ".join(sentences).strip()



# The only three next-step offers WaslaBot can actually follow through
# on (see prompt_builder.build_database_prompt rule 8). Rebuilding this
# line ourselves — instead of trusting the small local model to phrase
# and format it correctly every time — guarantees it always starts
# with "- " (so the frontend highlights it like every other follow-up
# question) and is never repeated once fulfilled.
#
# NOTE: deliberately avoid the words "profile"/"phone number"/
# "address"/"photo" here — those are the exact trigger words
# write_action_guard._OFFERED_ACTION_PATTERNS["profile"] looks for in
# WaslaBot's own last message, so a "more details about X's profile?"
# offer would make the guard mistake the user's next "yes" for
# confirming a profile *update* instead of an info lookup.
_OFFER_TEMPLATES = {
    "more_details": "Would you like more details about {name}?",
    "available_times": "Would you like to know {name}'s available appointment times?",
    "book": "Would you like the steps to book an appointment with {name}?",
}
_OFFER_ORDER = ["more_details", "available_times", "book"]

# Strips whatever offer-shaped line the LLM tried to end its answer
# with (correctly "- "-prefixed or not), so it can be replaced with the
# deterministic one below instead of ending up duplicated or malformed.
_TRAILING_OFFER_LINE_RE = re.compile(
    r"\n*[-•\s]*\b(would you like|do you want)\b[^\n]*\?\s*$",
    re.IGNORECASE
)


def _display_name(name):
    return name if re.match(r"^dr\.?\s", name, re.IGNORECASE) else f"Dr. {name}"


def _next_offer_line(chat_id, specialist_name):

    if not specialist_name:
        return ""

    fulfilled = get_fulfilled_offers(chat_id, specialist_name)

    for offer_type in _OFFER_ORDER:
        if offer_type not in fulfilled:
            template = _OFFER_TEMPLATES[offer_type]
            return f"\n\n- {template.format(name=_display_name(specialist_name))}"

    return ""


def _finalize_specialist_answer(answer, chat_id, specialist_name):
    """
    Drops any next-step question the LLM drafted and appends the
    correct, deterministically-formatted one instead — see
    _TRAILING_OFFER_LINE_RE / _next_offer_line above.
    """

    if not specialist_name:
        return answer

    return _TRAILING_OFFER_LINE_RE.sub("", answer).rstrip() + _next_offer_line(chat_id, specialist_name)


def _build_info_answer(offer_type, doc):
    """
    Builds the "more details" / "available times" answer directly from
    the specialist record instead of asking the LLM to compose it.

    The local model was leaking available-time data into "more
    details" answers (both were drawn from the same full-detail blob)
    and, separately, dropping slots when asked to list them back out —
    the same faithfulness problem write_action_guard exists to guard
    against elsewhere. Scoping the data AND building the sentence
    ourselves avoids both.
    """

    name = _display_name(doc.get("name") or "This specialist")

    if offer_type == "available_times":
        slots = doc.get("availableSlots") or []

        if not slots:
            return f"{name} doesn't have any available appointment times listed yet."

        return f"{name}'s available appointment times: {_format_slots(slots)}."

    rating = doc.get("rating", 0)
    fee = doc.get("consultationFee", "N/A")
    specialization = doc.get("specialization", "N/A")
    bio = doc.get("bio")

    answer = f"{name} is a {specialization} specialist rated {rating}/5, with a consultation fee of {fee}."

    if bio:
        answer += f" {bio}"

    return answer


_HOW_TO_BOOK_RE = re.compile(r"\bhow\b.{0,15}\bbook\b|\bsteps?\b.{0,15}\bbook\b", re.IGNORECASE)


def _find_all_mentioned_specialists(query, specialists):
    """
    Returns every one of the given specialists the user named in their
    message (matched loosely by first/last name), in the order they
    appear in `specialists`, de-duplicated.
    """

    query_lower = query.lower()
    found = []
    seen_ids = set()

    for doc in specialists:
        name = doc.get("name") or ""
        parts = [part for part in re.split(r"\s+", name.lower()) if len(part) > 2]

        if any(part in query_lower for part in parts):
            key = doc.get("_id", name)

            if key not in seen_ids:
                seen_ids.add(key)
                found.append(doc)

    return found


def _find_mentioned_specialist(query, specialists):
    """
    Returns whichever of the given specialists the user named in their
    message (matched loosely by first/last name), or None. Lets "book
    with dr omar" resolve straight to that one doctor instead of
    re-dumping the whole top-3 list the user is already past.
    """

    found = _find_all_mentioned_specialists(query, specialists)

    return found[0] if found else None


_TOP_RATED_RE = re.compile(
    r"\b(highest|top|best|number one|no\.?\s*1)\b.{0,20}\b(rate|rated|rating|doctors?|specialists?)\b",
    re.IGNORECASE
)


def _build_top_rated_answer(specialists):
    """
    Answers "highest/top/best rated" questions from data[0] directly —
    that list is already Mongo-sorted by rating desc, so this is always
    correct, unlike trusting the LLM to re-identify the top entry from
    formatted text (it has picked the wrong one before).
    """

    if not specialists:
        return None

    top = specialists[0]
    name = _display_name(top.get("name") or "Unknown")
    specialization = top.get("specialization") or "specialist"
    rating = top.get("rating", 0)

    return f"The highest-rated {specialization} specialist is **{name}**, with a rating of {rating} out of 5."


_LIST_SPECIALISTS_RE = re.compile(
    r"\blist\b|\bshow me\b|\branked?\b|\bsorted\b"
    r"|\ball\b.{0,15}\b(doctors?|specialists?|drs?|docs?)\b"
    # plural noun ("drs"/"docs"/"doctors"/"specialists") anywhere near
    # "top"/"highest"/"best" — e.g. "what are the top drs", "top rated
    # doctors" — plural wording means the user wants several, not one.
    r"|\b(top|highest|best)\b.{0,20}\b(doctors|specialists|drs|docs)\b"
    r"|\b(doctors|specialists|drs|docs)\b.{0,20}\b(top|highest|best)\b"
    # explicit plural correction — "i asked for doctors not doctor"
    r"|\b(doctors|specialists|drs|docs)\b.{0,15}\bnot\b.{0,15}\b(a\s+|one\s+)?(doctor|specialist|dr)\b",
    re.IGNORECASE
)


def _build_specialist_list_answer(specialists):
    """
    "List the cardiologists from top to lowest" wants readable, scannable
    output, not one run-on sentence — reuse the same "- " bullet format
    used everywhere else in this pipeline (which the frontend already
    highlights consistently), built from the already-sorted data
    instead of asking the LLM to reproduce a ranked list faithfully.
    """

    if not specialists:
        return None

    specialization = specialists[0].get("specialization") or "matching"

    lines = "\n".join(
        f"- **{_display_name(doc.get('name') or 'Unknown')}** — rating {doc.get('rating', 0)}/5"
        for doc in specialists
    )

    return f"Here are the {specialization} specialists, from highest to lowest rated:\n{lines}"


def _appointment_datetime(appt):
    """
    Returns a timezone-aware datetime for an appointment record, or
    None if the date is missing/unparseable. Handles both real
    datetime objects and ISO-formatted strings from Mongo.
    """

    date = appt.get("date")

    if isinstance(date, datetime):
        return date if date.tzinfo else date.replace(tzinfo=timezone.utc)

    if isinstance(date, str):
        try:
            parsed = datetime.fromisoformat(date.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    return None


def _build_appointments_answer(appointments):
    """
    Builds the "what are my appointments" answer directly from the
    data, splitting upcoming vs past by comparing each appointment's
    actual date to now — instead of asking the LLM to reason about
    dates from formatted text, which produced self-contradictory
    answers like "you have no upcoming appointments... however, you
    have an appointment on February 10th" in the same reply.
    """

    if not appointments:
        return "You have no appointments on record yet."

    now = datetime.now(timezone.utc)
    upcoming, past, undated = [], [], []

    for appt in appointments:
        dt = _appointment_datetime(appt)

        if dt is None:
            undated.append(appt)
        elif dt >= now:
            upcoming.append(appt)
        else:
            past.append(appt)

    def _line(appt):
        name = _display_name(appt.get("specialistName") or "Unknown doctor")
        dt = _appointment_datetime(appt)
        date_text = dt.strftime("%d %B %Y at %I:%M %p") if dt else "an unspecified date"
        appt_type = appt.get("type", "consultation")
        status = appt.get("status")
        status_text = f", {status}" if status else ""
        return f"- **{name}** — {date_text} ({appt_type}{status_text})"

    parts = []

    if upcoming:
        upcoming.sort(key=_appointment_datetime)
        plural = "s" if len(upcoming) != 1 else ""
        parts.append(
            f"You have {len(upcoming)} upcoming appointment{plural}:\n"
            + "\n".join(_line(a) for a in upcoming)
        )
    else:
        parts.append("You have no upcoming appointments scheduled.")

    if past:
        past.sort(key=_appointment_datetime, reverse=True)
        plural = "s" if len(past) != 1 else ""
        parts.append(
            f"Past appointment{plural} on record:\n"
            + "\n".join(_line(a) for a in past)
        )

    if undated:
        parts.append(
            "Additional appointment record(s) with no clear date:\n"
            + "\n".join(_line(a) for a in undated)
        )

    return "\n\n".join(parts)


_COMPARISON_RE = re.compile(
    r"\b(higher|highest|better|compare|versus)\b|\bvs\b|\brate\b|\brating\b",
    re.IGNORECASE
)


def _handle_rating_comparison(query):
    """
    "Who has the higher rate, dr X or dr Y?" needs real records looked
    up by name — the normal SPECIALISTS routing only fires when a
    specialization keyword is present, so without this a comparison
    query reaches the LLM with no data at all, and it has been known to
    just invent plausible-looking numbers instead of saying so.
    """

    if not _COMPARISON_RE.search(query):
        return None

    mentioned = _find_all_mentioned_specialists(query, get_approved_specialists())

    if len(mentioned) < 2:
        return None

    sentences = " ".join(
        f"{_display_name(doc.get('name') or 'Unknown')} has a rating of {doc.get('rating', 0)}."
        for doc in mentioned
    )

    winner = max(mentioned, key=lambda doc: doc.get("rating", 0))
    winner_name = _display_name(winner.get("name") or "Unknown")

    return f"{sentences} **{winner_name}** has the higher rating."


def _handle_book_guidance(user_query, chat_id):
    """
    "Book an appointment" is never a dead end: if the user hasn't named
    a specialty yet, ask for it; once we know it, show the top-rated
    matches with real data and point at the actual Book Appointment
    button, instead of an immediate "I can't do that".
    """

    # A generic "how/what are the steps to book" is a procedural
    # question, not a request to search for a doctor — answer it
    # directly instead of falling back to whatever specialty happened
    # to be mentioned earlier in the conversation, which would just
    # re-run the same doctor search (and give the identical answer)
    # every single time this is asked.
    if _HOW_TO_BOOK_RE.search(user_query):
        return (
            "To book an appointment: open the specialist's profile page "
            "(from the Doctors list) and use the **Book Appointment** "
            "button there to pick an available date and time. You can "
            "also reach your upcoming and past appointments from your "
            "own Patient Profile page.\n\n"
            "- Which specialty are you looking for? I can help you find a doctor to book with."
        )

    specialization = (
        extract_specialization(user_query)
        or extract_specialization(get_history(chat_id))
    )

    if not specialization:
        return (
            "- I can't book it myself, but I can help you find the right "
            "specialist first. Which specialty are you looking for (e.g. "
            "cardiology, dermatology, pediatrics)?"
        )

    matches = get_specialists_by_specialization(specialization)

    if not matches:
        return f"I couldn't find any approved {specialization} specialists right now."

    mentioned = _find_mentioned_specialist(user_query, matches)

    if mentioned:
        name = mentioned.get("name", "the specialist")
        set_last_specialist_name(chat_id, name)
        mark_offer_fulfilled(chat_id, name, "book")

        slots = mentioned.get("availableSlots") or []
        slot_text = f" Available times: {_format_slots(slots)}." if slots else ""

        # The times were just given inline above — don't offer them
        # again as a separate next step.
        if slots:
            mark_offer_fulfilled(chat_id, name, "available_times")

        answer = (
            f"Great choice — open **{_display_name(name)}**'s profile "
            f"(from the Doctors list) and use the **Book Appointment** "
            f"button there to pick a date and time. You can also view "
            f"this booking afterward from your own Patient Profile "
            f"page.{slot_text}"
        )

        return answer + _next_offer_line(chat_id, name)

    top = matches[:3]
    top_name = top[0].get("name", "the top specialist")
    set_last_specialist_name(chat_id, top_name)

    lines = "\n".join(
        f"- **{doc.get('name', 'Unknown')}** — rating {doc.get('rating', 0)}, "
        f"fee {doc.get('consultationFee', 'N/A')}"
        for doc in top
    )

    # Giving these steps here IS fulfilling the "book" offer — never
    # ask it again for this specialist in this conversation.
    mark_offer_fulfilled(chat_id, top_name, "book")

    answer = (
        f"Here are the top-rated {specialization} specialists:\n{lines}\n\n"
        "Once you've picked one, open their profile from the Doctors "
        "list and use the **Book Appointment** button there to choose "
        "an available date and time. You can also view your bookings "
        "afterward from your own Patient Profile page."
    )

    return answer + _next_offer_line(chat_id, top_name)


def _handle_existing_appointment_guidance(action, chat_id):
    """
    Cancel/reschedule are about an appointment the user already has —
    show them what's upcoming first so they know which one, then the
    real steps, instead of a bare "I can't do that".
    """

    user_id = get_user(chat_id)

    if not user_id:
        return build_action_guard_message(action, logged_in=False)

    upcoming = get_patient_upcoming_appointments(user_id)

    if not upcoming:
        verb = "cancel" if action == "cancel" else "reschedule"
        return f"You don't have any upcoming appointments to {verb}."

    lines = "\n".join(
        f"- **{appt.get('specialistName') or 'Unknown'}** "
        f"({appt.get('specialization', 'N/A')}) — {_safe_date(appt.get('date'))}, "
        f"status {appt.get('status', 'unknown')}"
        for appt in upcoming
    )

    return (
        f"Here are your upcoming appointments:\n{lines}\n\n"
        + build_action_guard_message(action, logged_in=True)
    )


def predict(user_query, chat_id="default_session"):
    """
    Main chatbot pipeline
    """

    # -------------------------
    # init model
    # -------------------------
    initialize_model()

    # -------------------------
    # clean input
    # -------------------------
    processed_query = clean_query(user_query)

    # -------------------------
    # gibberish check (on raw input — spell-correction can turn
    # nonsense like "gvh" into a real word like "get" and hide it)
    # -------------------------
    if is_gibberish(user_query, chat_id):

        answer = "I couldn't understand your message. Could you rephrase it?"

        # add_message(chat_id, "user", user_query)
        
        
        add_message(chat_id, "assistant", answer)
        set_waiting_for_reply(chat_id, assistant_is_waiting(answer))


        return {
            "answer": answer,
            "sources": [],
            "confidence": 0.0
        }

    # -------------------------
    # save user message
    # -------------------------
    add_message(chat_id, "user", user_query)

    # -------------------------
    # login-offer follow-up — deterministic, no LLM call
    # -------------------------
    if is_pending_login_offer(chat_id):

        clear_pending_login_offer(chat_id)

        if _AFFIRMATIVE_RE.match(user_query.strip()):

            answer = (
                "To log in:\n\n"
                "1. Open the Med-Wasla login page.\n"
                "2. Enter your registered email and password.\n"
                "3. Click Log In.\n\n"
                "If you've forgotten your password, use the Forgot "
                "Password option on the login page."
            )

            add_message(chat_id, "assistant", answer)
            set_waiting_for_reply(chat_id, False)

            return {
                "answer": answer,
                "sources": [],
                "confidence": 1.0
            }

    # -------------------------
    # sensitive info guard — refuse before touching the database at all
    # -------------------------
    if is_sensitive_request(user_query):

        add_message(chat_id, "assistant", REFUSAL_MESSAGE)
        set_waiting_for_reply(chat_id,assistant_is_waiting(REFUSAL_MESSAGE))

        return {
            "answer": REFUSAL_MESSAGE,
            "sources": [],
            "confidence": 1.0
        }

    # -------------------------
    # write action guard — the chatbot has no write access to the
    # database at all (no booking, cancelling, rescheduling, password/
    # email/profile changes); never let the LLM pretend it did one
    # -------------------------
    requested_action = get_requested_action(processed_query, chat_id)

    if requested_action == "book":

        answer = _handle_book_guidance(processed_query, chat_id)

        add_message(chat_id, "assistant", answer)
        set_waiting_for_reply(chat_id, assistant_is_waiting(answer))


        return {
            "answer": answer,
            "sources": ["MongoDB"],
            "confidence": 1.0
        }

    if requested_action in ("cancel", "reschedule"):

        answer = _handle_existing_appointment_guidance(requested_action, chat_id)

        add_message(chat_id, "assistant", answer)
        set_waiting_for_reply(chat_id, assistant_is_waiting(answer))


        return {
            "answer": answer,
            "sources": ["MongoDB"],
            "confidence": 1.0
        }

    if requested_action:

        user_id = get_user(chat_id)

        answer = build_action_guard_message(requested_action, logged_in=bool(user_id))

        add_message(chat_id, "assistant", answer)
        set_waiting_for_reply(chat_id, assistant_is_waiting(answer))


        return {
            "answer": answer,
            "sources": ["Med-Wasla"],
            "confidence": 1.0
        }

    # -------------------------
    # the user confirmed a "more details" / "available times" offer
    # WaslaBot made about a specialist it already named — unlike the
    # write actions above, this IS something we can actually fetch.
    # -------------------------
    requested_info = get_requested_info(processed_query, chat_id)

    if requested_info:

        specialist_name = get_last_specialist_name(chat_id)
        doc = get_specialist_by_name(specialist_name) if specialist_name else None

        if not doc:
            answer = (
                "I don't have a specific specialist in mind anymore — "
                "which doctor did you mean?"
            )
        else:
            answer = _build_info_answer(requested_info, doc)

            mark_offer_fulfilled(chat_id, specialist_name, requested_info)
            answer = _finalize_specialist_answer(answer, chat_id, specialist_name)

        add_message(chat_id, "assistant", answer)
        set_waiting_for_reply(chat_id, assistant_is_waiting(answer))


        return {
            "answer": answer,
            "sources": ["MongoDB"],
            "confidence": 1.0
        }

    # -------------------------
    # "who has the higher rate, dr X or dr Y?" — needs real records
    # looked up by name; the small local model has fabricated ratings
    # outright when this reached it with no data.
    # -------------------------
    comparison_answer = _handle_rating_comparison(processed_query)

    if comparison_answer:

        add_message(chat_id, "assistant", comparison_answer)
        set_waiting_for_reply(chat_id, assistant_is_waiting(comparison_answer))

        return {
            "answer": comparison_answer,
            "sources": ["MongoDB"],
            "confidence": 1.0
        }

    # -------------------------
    # any other made-up offer the LLM confirmed — e.g. "would you like
    # to see more details?" -> "yes" -> model hallucinates having
    # emailed/sent/notified something. Catch it even though we don't
    # recognize the specific offer.
    # -------------------------
    if is_unrecognized_offer_confirmation(processed_query, chat_id):

        add_message(chat_id, "assistant", GENERIC_NO_ACTION_MESSAGE)
        set_waiting_for_reply(chat_id,assistant_is_waiting(GENERIC_NO_ACTION_MESSAGE))

        return {
            "answer": GENERIC_NO_ACTION_MESSAGE,
            "sources": [],
            "confidence": 1.0
        }


    # -------------------------
    # Detect whether this looks like a reply to the previous assistant message
    # -------------------------

    from memory.session import is_waiting_for_reply

    history = get_history(chat_id)

    is_followup = (
        len(processed_query.split()) <= 12
        and (
            is_waiting_for_reply(chat_id)
            # A medical conversation naturally continues with related
            # follow-ups ("do I need to do anything in the meantime?")
            # even after a wrap-up summary that didn't end in a literal
            # question — don't lose that context and fall back to the
            # context-blind classifier just because assistant_is_waiting
            # happened to be False.
            or get_last_question_type(chat_id) == "MEDICAL"
        )
    )

    # -------------------------
    # Routing
    # -------------------------

    if is_followup:

        question_type = keyword_route(processed_query)

        if question_type is None:
            question_type = get_last_question_type(chat_id)

            if question_type is None:
                question_type = classify_question(processed_query)

    else:

        question_type = keyword_route(processed_query)

        if question_type is None:
            question_type = classify_question(processed_query)

    print(f"Question Type: {question_type}")
    
    if question_type == "MEDICAL":
        set_conversation_state(chat_id, "COLLECTING_SYMPTOMS")

    elif question_type == "DATABASE":
        set_conversation_state(chat_id, "DATABASE")
        set_phase(chat_id, None)
        clear_expected_answer(chat_id)

    elif question_type == "CHITCHAT":
        set_conversation_state(chat_id, "CHITCHAT")
        set_phase(chat_id, None)
        clear_expected_answer(chat_id)

    elif question_type == "GENERAL":
        set_phase(chat_id, None)
        clear_expected_answer(chat_id)
    
    if question_type != "GENERAL":
        set_last_question_type(chat_id, question_type)
        
    # -------------------------
    # chitchat (predefined exact-match responses)
    # -------------------------
    chitchat_answer = get_chitchat_response(processed_query)

    if chitchat_answer:

        add_message(chat_id, "assistant", chitchat_answer)
        set_waiting_for_reply(chat_id, assistant_is_waiting(chitchat_answer))

        return {
            "answer": chitchat_answer,
            "sources": [],
            "confidence": 1.0
        }

    # -------------------------
    # chitchat (classified as CHITCHAT but no exact-match phrase)
    # -------------------------
    if question_type == "CHITCHAT":

        history = get_history(chat_id)

        prompt = build_chitchat_prompt(
            processed_query,
            history
        )
        try:
            print("\n" + "=" * 80)
            print("FINAL PROMPT SENT TO LLM")
            print("=" * 80)
            print(prompt)
            print("=" * 80 + "\n")

            answer = generate_response(prompt)
            answer = _strip_leaked_planner_block(answer)

            planner = get_next_missing_information(chat_id)

            if planner and planner["field"]:
                set_expected_answer(chat_id, planner["field"])

                question_text = get_followup_question(chat_id, planner)

                if question_text:
                    answer = _strip_trailing_questions(answer)
                    answer = f"{answer.rstrip()}\n\n- {question_text}"
        
        except Exception as e:
            print("Chitchat Error:", e)
            answer = "Hello! How can I help you today?"

        lower_answer = answer.lower()

        if "scale of 1-10" in lower_answer or "scale from 1 to 10" in lower_answer:
            set_expected_answer(chat_id, "pain_scale")

        elif "how long" in lower_answer:
            set_expected_answer(chat_id, "duration")

        add_message(chat_id, "assistant", answer)
        set_waiting_for_reply(chat_id, assistant_is_waiting(answer))


        return {
            "answer": answer,
            "sources": [],
            "confidence": 1.0
        }

    # -------------------------
    # general / off-topic
    # -------------------------
    if question_type == "GENERAL":

        answer = "It looks like your question is not related to Med-Wasla or health."

        add_message(chat_id, "assistant", answer)
        set_waiting_for_reply(chat_id, assistant_is_waiting(answer))


        return {
            "answer": answer,
            "sources": [],
            "confidence": 0.0
        }

    # =========================
    # DATABASE CONTEXT (only if enabled)
    # =========================
    user_context = None
    context_specialist_name = None
    context_specialists = None
    context_appointments = None
    user_id = None

    if ENABLE_DATABASE:
        user_id = get_user(chat_id)

        try:
            user_context, context_specialist_name, context_specialists, context_appointments = get_user_context(
                processed_query, user_id, chat_id
            )
        except Exception as e:
            print("Database Error:", e)

    # =========================
    # DATABASE RESPONSE
    # =========================
    if question_type == "DATABASE":

        if not user_id:

            answer = (
                "Unfortunately, you need to be logged in to access "
                "your account and platform data. Please log in to "
                "view this information.\n\n"
                "- Would you like to know how to log in?"
            )

            set_pending_login_offer(chat_id)

            add_message(chat_id, "assistant", answer)
            set_waiting_for_reply(chat_id, True)

            return {
                "answer": answer,
                "sources": [],
                "confidence": 1.0
            }

        # "what are my appointments" — build the upcoming/past split
        # deterministically from the real dates, instead of letting the
        # LLM reason about dates from formatted text (it has produced
        # self-contradictory answers like "no upcoming appointments...
        # however you have one on February 10th" in the same reply).
        if context_appointments is not None:

            answer = _build_appointments_answer(context_appointments)

            add_message(chat_id, "assistant", answer)
            set_waiting_for_reply(chat_id, assistant_is_waiting(answer))

            return {
                "answer": answer,
                "sources": ["MongoDB"],
                "confidence": 1.0
            }

        # "list the cardiologists from top to lowest" — a readable
        # bulleted ranking, not a single pick. Checked before the
        # single-winner case below since "list ... top to lowest" would
        # otherwise also look like a "top rated" question.
        if context_specialists and _LIST_SPECIALISTS_RE.search(processed_query):

            answer = _build_specialist_list_answer(context_specialists)
            list_top_name = context_specialists[0].get("name")

            if list_top_name:
                set_last_specialist_name(chat_id, list_top_name)

            answer = _finalize_specialist_answer(answer, chat_id, list_top_name)

            add_message(chat_id, "assistant", answer)
            set_waiting_for_reply(chat_id, assistant_is_waiting(answer))


            return {
                "answer": answer,
                "sources": ["MongoDB"],
                "confidence": 1.0
            }

        # "highest/top/best rated" — answer from the already-sorted
        # data directly instead of trusting the LLM to re-identify the
        # top entry from formatted text (it has picked the wrong one).
        if context_specialists and _TOP_RATED_RE.search(processed_query):

            answer = _build_top_rated_answer(context_specialists)
            top_rated_name = context_specialists[0].get("name")

            if top_rated_name:
                set_last_specialist_name(chat_id, top_rated_name)

            answer = _finalize_specialist_answer(answer, chat_id, top_rated_name)

            add_message(chat_id, "assistant", answer)
            set_waiting_for_reply(chat_id, assistant_is_waiting(answer))


            return {
                "answer": answer,
                "sources": ["MongoDB"],
                "confidence": 1.0
            }

        history = get_history(chat_id)

        prompt = build_database_prompt(
            user_query=user_query,
            history_buffer=history,
            symptom_summary=get_symptom_summary(chat_id),
            user_context=user_context
        )

        try:
            answer = generate_response(prompt)
            answer = _strip_leaked_planner_block(answer)
            answer = _finalize_specialist_answer(answer, chat_id, context_specialist_name)

        except Exception as e:
            print("DB Error:", e)
            answer = "Sorry, I couldn't retrieve your account information."

        
        add_message(chat_id, "assistant", answer)
        set_waiting_for_reply(chat_id, assistant_is_waiting(answer))


        return {
            "answer": answer,
            "sources": ["MongoDB"],
            "confidence": 1.0
        }

    # =========================
    # RAG RETRIEVAL (MEDICAL/WEBSITE)
    # =========================
    
    # Build retrieval query
    retrieval_query = processed_query

    if is_followup:
        symptom_summary = get_symptom_summary(chat_id)

        if symptom_summary:
            retrieval_query = f"""
    Current confirmed symptoms:
    {symptom_summary}
    Latest user reply:
    {processed_query}
    """
        else:
            retrieval_query = f"""
    Conversation:
    {history}
    Latest user reply:
    {processed_query}
    """

    filtered_docs, confidence, sources = retrieve_documents(
        question_type,
        retrieval_query
    )

    if not filtered_docs:

        answer = "It looks like your question is not related to Med-Wasla or health."

        add_message(chat_id, "assistant", answer)
        set_waiting_for_reply(chat_id, assistant_is_waiting(answer))


        return {
            "answer": answer,
            "sources": [],
            "confidence": 0.0
        }

    if confidence < SIMILARITY_THRESHOLD and not is_followup:
        answer = "I couldn't find enough reliable information."

        
        add_message(chat_id, "assistant", answer)
        set_waiting_for_reply(chat_id, assistant_is_waiting(answer))


        return {
            "answer": answer,
            "sources": [],
            "confidence": round(float(confidence), 3)
        }

    # =========================
    # FINAL PROMPT BUILD
    # =========================
    
    planner = get_next_missing_information(chat_id)

    followup_guidance = None

    if planner:
        followup_guidance = get_followup_guidance(chat_id, planner)

        if planner["priority"] == "emergency":
            set_phase(chat_id, EMERGENCY)

        elif planner["priority"] == "complete":
            set_phase(chat_id, ENOUGH_INFORMATION)

        else:
            set_phase(chat_id, COLLECTING_SYMPTOMS)

    conversation_state = get_conversation_state(chat_id)


    phase = get_phase(chat_id)

    if phase == EMERGENCY:

        prompt = f"""
    You are WaslaBot.

    The patient has already reported emergency warning signs earlier in the conversation.

    Your role now is to continue the conversation naturally.

    Rules:

    Your ONLY task is:

    1. Briefly acknowledge the patient's latest reply.
    2. Clearly explain that the reported symptoms require immediate emergency medical care.
    3. Give 3–5 brief, practical first-aid or self-care recommendations that are safe to follow while waiting for medical care or traveling to the emergency department, formatted as a NUMBERED LIST, one per line — for example:
    1. Avoid strenuous physical activity.
    2. Sit upright if breathing is difficult.
    3. Stay with another person if possible.
    4. Do not drive yourself if symptoms are severe.
    5. Call emergency services if symptoms worsen.
    4. Do NOT write these recommendations as inline prose or a single paragraph — always as a numbered list like the example above.
    5. Do NOT suggest home treatment instead of emergency care.
    6. Do NOT discuss diagnoses in detail.
    7. Do NOT ask further medical questions.
    8. Keep the response under 8 sentences.

    - First acknowledge the patient's latest reply in one short sentence.
    - If they answered a previous question, briefly acknowledge the answer.
    - Do NOT repeat the exact same wording as your previous response.
    - Remind them that their symptoms may require immediate emergency medical care.
    - Encourage them to go to the nearest emergency department or call local emergency services.
    - Do NOT ask any more medical questions.
    - Do NOT discuss diagnoses.
    - Keep the reply under 5 sentences.
    - Make each reply sound slightly different from the previous one.

    Recent conversation:
    {history}

    Latest user message:
    {user_query}
    """

    else:

        prompt = build_combined_prompt(
            context_docs=filtered_docs,
            user_query=user_query,
            history_buffer=history,
            symptom_summary=get_symptom_summary(chat_id),
            conversation_state=conversation_state,
            planner=planner,
            followup_guidance=followup_guidance,
            causes_already_explained=has_explained_causes(chat_id),
            user_context=user_context
        )

    try:
        answer = generate_response(prompt)
        answer = _strip_leaked_planner_block(answer)

        if planner and planner["field"] and phase != EMERGENCY:
            set_expected_answer(chat_id, planner["field"])

            question_text = get_followup_question(chat_id, planner)

            if question_text:
                answer = _strip_trailing_questions(answer)
                answer = f"{answer.rstrip()}\n\n- {question_text}"

        if phase != EMERGENCY:
            mark_causes_explained(chat_id)

    except Exception as e:
        print("Ollama Error:", e)
        answer = "Sorry, I couldn't generate a response."

    add_message(chat_id, "assistant", answer)

    if phase == EMERGENCY:
        set_waiting_for_reply(chat_id, False)
    else:
        set_waiting_for_reply(chat_id, assistant_is_waiting(answer))

    return {
        "answer": answer,
        "sources": sources,
        "confidence": round(float(confidence), 3)
    }