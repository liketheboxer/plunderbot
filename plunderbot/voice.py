"""PlunderBot's voice: a bright, bubbly robot butler who swears like a (polite) pirate.

Every member-facing line lives here so the voice stays consistent and is easy to tune.
Admin replies and logs stay in plain English on purpose; they live in the cogs.

Lines are templates for str.format(). Keep them original: no lyrics or quotes from songs,
films or the game's own characters.
"""
from __future__ import annotations

import random

CUSSES = [
    "Barnacles!",
    "Blistering bilge rats!",
    "Sink me!",
    "Shiver me circuits!",
    "Scuttle it all!",
    "Son of a sea biscuit!",
    "Mother of all mermaids!",
    "Great galloping gangplanks!",
    "Rust and rigging!",
]

LINES: dict[str, list[str]] = {
    "about": [
        "PlunderBot at your service! Pirate Logistics, Unsolicited Nautical Drivel & Event Reminders, "
        "version {version}. Polished, oiled and ready to fetch your grog.",
        "Ahoy! PlunderBot {version}, butler to Brimstone Hill Fortress. I keep the calendar, the crews "
        "and the cake schedule shipshape.",
    ],
    "birthday_set": [
        "Splendid! I've written {date} in the ship's ledger. Expect cake, fanfare and at least one cannon salute.",
        "Noted with great enthusiasm: {date}! I shall polish the party cannon.",
        "{date}, logged and locked in the captain's chest. Oh, I do love a birthday!",
    ],
    "birthday_changed": [
        "{cuss} A change of course! Your birthday is now {date}. The ledger has been lovingly corrected.",
        "Updated to {date}! I've crossed out the old one very neatly, promise.",
    ],
    "birthday_removed": [
        "Done! Your birthday has walked the plank. No cake, no fuss, no hard feelings.",
        "Struck from the ledger! I'll miss the cake, but your secret is safe with me.",
    ],
    "birthday_not_found": [
        "{cuss} I've searched every barrel and there's no birthday of yours in the ledger yet. "
        "Try `/birthday set` whenever you like!",
    ],
    "birthday_invalid": [
        "{cuss} {month_name} doesn't have a day {day}, not even on the high seas. Try again?",
        "{cuss} My charts say {month_name} stops before day {day}. Give it another go!",
    ],
    "birthday_too_soon": [
        "{cuss} You changed your birthday recently, so the ledger's locked until {date}. "
        "If it's wrong, a Quartermaster can help!",
    ],
    "birthday_mine": [
        "Your birthday is {date} in my ledger. To change it, just run `/birthday set` again.",
    ],
    "birthday_toast_one": [
        "Hoist the colours! It's {names}'s birthday! Happy birthday from your devoted butler "
        "and the whole crew of Brimstone Hill Fortress!",
        "{cuss} Would you look at the date! Happy birthday, {names}! May your sails be full and "
        "your chests fuller.",
        "Fire the cake cannon! Happy birthday, {names}! The grog's on the house (the house is imaginary).",
    ],
    "birthday_toast_many": [
        "Hoist the colours! We've a whole crew of birthdays today: {names}! "
        "Happy birthday from your devoted butler!",
        "{cuss} A birthday fleet! Happy birthday to {names}! I've baked a cake for each of you. "
        "Metaphorically. I'm a robot.",
    ],
    "birthdays_upcoming_header": [
        "Upcoming birthdays on the ship's calendar:",
        "Here's who's due for cake:",
    ],
    "birthdays_none": [
        "The birthday ledger is empty as a sunk chest! Add yours with `/birthday set`.",
    ],
    "guild_only": [
        "{cuss} That order only works aboard the ship, not in private messages.",
    ],
    "error": [
        "{cuss} Something jammed in my gears. I've reported it to the Quartermasters. Try again in a moment?",
        "{cuss} I tripped over the anchor chain. The Quartermasters have been told; please try again shortly.",
    ],
    "no_permission": [
        "{cuss} That lever is for Quartermasters only, I'm afraid!",
    ],
}

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"]


def cuss(rng: random.Random | None = None) -> str:
    return (rng or random).choice(CUSSES)


def say(key: str, rng: random.Random | None = None, **values) -> str:
    """Pick a line for `key` and fill it in. `{cuss}` is always available."""
    r = rng or random
    template = r.choice(LINES[key])
    values.setdefault("cuss", cuss(r))
    return template.format(**values)


def format_date(month: int, day: int) -> str:
    return f"{MONTH_NAMES[month - 1]} {day}"


def join_names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f" and {names[-1]}"
