from database.services.database_router import handle_database_query
from database.services.database_formatter import (
    format_appointments,
    format_reviews,
    format_specialists
)
from memory.session import set_last_specialist_name


def get_user_context(user_query, user_id, chat_id=None):
    """
    Returns (context_text, specialist_name, specialist_list, appointments).

    specialist_name is the top specialist the response is about, or
    None when the answer isn't about a single specialist — callers use
    it to know whether a next-step offer ("more details"/"available
    times"/"steps to book") makes sense to attach.

    specialist_list is the raw, Mongo-sorted (by rating desc) list of
    matched specialists when the intent was SPECIALISTS, or None
    otherwise — callers use it to answer "highest rated" questions by
    reading data[0] directly instead of trusting the LLM to correctly
    pick the top entry back out of formatted text.

    appointments is the raw list of appointment records when the
    intent was APPOINTMENTS, or None otherwise — callers use it to
    determine upcoming vs past appointments deterministically, instead
    of trusting the LLM to correctly reason about dates from formatted
    text (it has said "no upcoming appointments" and then immediately
    listed one in the same reply).
    """

    result = handle_database_query(user_query, user_id)

    if result is None:
        return "", None, None, None

    if result["type"] == "appointments":
        appointments = result["data"] or []
        return format_appointments(appointments), None, None, appointments

    if result["type"] == "specialists":
        specialists = result["data"] or []
        specialist_name = specialists[0].get("name") if specialists else None

        if chat_id and specialist_name:
            set_last_specialist_name(chat_id, specialist_name)

        return format_specialists(specialists), specialist_name, specialists, None

    if result["type"] == "reviews":
        return format_reviews(result["data"]), None, None, None

    if result["type"] == "login_required":
        return (
            "The user is not logged in, so this information is not available. Tell them to log in to see this.",
            None,
            None,
            None
        )

    return "", None, None, None
