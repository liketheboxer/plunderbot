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
    "crew_call": [
        "Ahoy! {captain} is mustering a crew for {game}. Hop aboard!",
        "All hands! {captain} needs a crew for {game}. Seats are filling fast!",
        "Splendid news! {captain} is raising a {size} for {game}. Who's in?",
    ],
    "hangout_call": [
        "{captain} is hanging out in voice for some parallel play. Bring your own game and keep them company!",
        "Hangout ahoy! {captain} is in voice doing their own thing. Everyone's welcome, whatever you're playing!",
    ],
    "hangout_started": [
        "Your hangout is open and the voice channel is going up now. Enjoy the company!",
    ],
    "crew_ping": [
        "{role}, a crew is forming!",
        "Calling all {role}! There's a ship that needs you.",
    ],
    "crew_started": [
        "Your crew call is up! I'll set sail the moment it's full, or whenever you press Set Sail.",
    ],
    "crew_joined": [
        "Welcome aboard! Mind the barnacles.",
        "You're on the manifest! Splendid!",
        "Aboard and accounted for. {cuss} This is going to be fun!",
    ],
    "crew_joined_sailing": [
        "Welcome aboard! Your crew is already at sea: head to {channel}.",
    ],
    "crew_left": [
        "Off the manifest you go. Fair winds, friend!",
        "Understood! I've freed your seat for another sailor.",
    ],
    "crew_full": [
        "{cuss} That crew is full to the gunwales. Try another, or start your own with `/crew start`!",
    ],
    "crew_already_aboard": [
        "You're already aboard this one! I'd never lose track of a crewmate.",
    ],
    "crew_not_aboard": [
        "You're not on this crew's manifest, so there's nothing to leave!",
    ],
    "crew_captain_leave": [
        "Captains can't abandon ship! Use Close if the voyage is off.",
    ],
    "crew_captain_only": [
        "{cuss} Only the captain can give that order.",
    ],
    "crew_over": [
        "{cuss} That crew call has already ended. Start a fresh one with `/crew start`!",
    ],
    "crew_one_at_a_time": [
        "{cuss} You're already captaining a crew! Close that one first, or keep sailing with it.",
    ],
    "crew_bad_size": [
        "{cuss} {game} crews come in these sizes: {options}.",
    ],
    "crew_bad_activity": [
        "{cuss} I don't know that one for {game}. Pick from: {options}.",
    ],
    "crew_sailing": [
        "Anchors aweigh! {names}, your voice channel is ready: {channel}",
        "Hoist the sails! {names}, gather in {channel} and have a splendid voyage!",
    ],
    "crew_sailing_no_voice": [
        "Anchors aweigh, {names}! {cuss} I couldn't open a voice channel, so a Quartermaster should check my permissions.",
    ],
    "crew_closed": [
        "Crew call closed. Back to port we go!",
    ],
    "crew_no_threads": [
        "{cuss} Crew calls need a regular text channel, not a thread. Try the main channel!",
    ],
    "crew_cant_post": [
        "{cuss} I can't post a crew card here. A Quartermaster needs to give me Send Messages and Embed Links in this channel.",
    ],
    "crew_renamed": [
        "Splendid name! The card's updated, and the voice channel follows as soon as Discord lets me.",
    ],
    "crew_none": [
        "No crews are mustering right now. Start one with `/crew start`!",
    ],
    "crew_list_header": [
        "Crews on the water:",
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
