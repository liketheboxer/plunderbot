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
    "crew_posted_there": [
        "Your crew card is up in the crew channel: {link}",
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
    "image_bad": [
        "{cuss} I can't hang that on the card. Send a PNG, JPG, GIF or WEBP picture, up to 10 MB, please!",
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
    "voyage_posted": [
        "Hear ye! {organizer} is planning a voyage: **{title}**. Tell the butler if you're aboard!",
        "A voyage is on the charts! {organizer} has scheduled **{title}**. RSVP below, if you please!",
    ],
    "voyage_created": [
        "Voyage scheduled for {when}! Reminders go out {reminders}, and I'll open a voice channel at the start. {link}",
    ],
    "voyage_aboard": [
        "You're aboard **{title}**! I'll remind you before we sail.",
        "Splendid! One more hand on deck for **{title}**.",
    ],
    "voyage_waitlist": [
        "{cuss} **{title}** is full, so you're on the waitlist. I'll shout the moment a seat opens!",
    ],
    "voyage_maybe": [
        "Marked as maybe for **{title}**. I'll keep you in the loop!",
    ],
    "voyage_cant": [
        "No worries! Marked as can't make it for **{title}**. Next time!",
    ],
    "voyage_removed": [
        "Answer cleared! Pick again any time.",
    ],
    "voyage_promoted": [
        "Good news, {names}! A seat opened up on **{title}** and you're aboard!",
    ],
    "voyage_reminder": [
        "Ahoy {names}! **{title}** sets sail {when}. {link}",
        "A friendly nudge from your butler, {names}: **{title}** is {when}! {link}",
    ],
    "voyage_sailing_role": [
        "{role}, **{title}** is setting sail right now! Hop into {channel} to join or watch.",
        "Anchors aweigh, {role}! **{title}** is sailing. Come aboard or spectate in {channel}.",
    ],
    "voyage_starting_maybe": [
        "{names}, **{title}** is starting now! Come aboard in {channel} if you can make it.",
    ],
    "voyage_cancelled": [
        "{cuss} **{title}** has been cancelled. Sorry, {names}!",
    ],
    "voyage_cancel_done": [
        "Voyage cancelled, and everyone who'd answered has been told.",
    ],
    "voyage_edited": [
        "Voyage updated, and the Discord Event with it. It's now {when}. {link}",
    ],
    "voyage_nothing_changed": [
        "You didn't give me anything to change! Pick at least one thing to update.",
    ],
    "voyage_bad_input": [
        "{cuss} {error}",
    ],
    "voyage_bad_time": [
        "{cuss} That time is in the past or more than a year away. Pick a time in the future!",
    ],
    "voyage_not_yours": [
        "{cuss} Only the organizer or a Quartermaster can change that voyage.",
    ],
    "voyage_none": [
        "{cuss} I can't find that voyage. It may have already sailed or been cancelled.",
    ],
    "voyage_over": [
        "{cuss} That voyage has already sailed or been cancelled.",
    ],
    "voyage_none_upcoming": [
        "Nothing on the charts yet! Schedule one with `/voyage create`.",
    ],
    "voyage_list_header": [
        "Voyages on the charts:",
    ],
    "tz_saved": [
        "Got it! I'll read the times you type as {zone}. It's {local} there right now. Everyone else still "
        "sees times in their own zone.",
    ],
    "tz_unknown": [
        "{cuss} I don't know the time zone \"{zone}\". Try Pacific, ET, America/Chicago or Europe/London.",
    ],
    "tz_mine": [
        "I read the times you type as {zone}. It's {local} there right now.",
    ],
    "tz_none": [
        "You haven't set a time zone, so I read the times you type as the server's: {zone}. "
        "Set yours with `/timezone set`, or by picking a region role.",
    ],
    "tz_mine_region": [
        "Your region role says {zone}, so that's how I read the times you type. It's {local} there right now. "
        "Not quite right? Pick your exact zone with `/timezone set`.",
    ],
    "tz_cleared_region": [
        "Forgotten! I'll go by your region role again: {zone}.",
    ],
    "tz_cleared": [
        "Forgotten! I'll read your times in the server's time zone again.",
    ],
    "gangplank_welcome": [
        "Welcome aboard **{server}**, {member}! First, have a good read of the rules in {rules}. Then show us "
        "you're not a bot (takes one to know one!): introduce yourself right here and tell us your favorite game.",
        "Ahoy, {member}, and welcome to **{server}**! Step one: read the rules in {rules}, properly now. Step two: "
        "prove you're flesh and grog, not bolts like me, by introducing yourself here and telling us your "
        "favorite game.",
    ],
    "gangplank_approved": [
        "Thanks for introducing yourself, {member}, and welcome aboard! Head over to {orientation} to pick "
        "your roles, and grab a region role while you're there so every voyage time shows in your own time zone.",
        "{member} is aboard! Welcome to the Fortress! Swing by {orientation} to pick your roles, and don't "
        "skip the region role: it's how I show you every time in your own time zone.",
    ],
    "gangplank_approved_buttons": [
        "Thanks for introducing yourself, {member}, and welcome aboard! Pick your region and roles with the "
        "buttons below (only you see your picks), and swing by {orientation} for the Pirate's Guide.",
        "{member} is aboard! Welcome to the Fortress! Use the buttons below to pick your region, so every time "
        "shows in your own time zone, plus your roles and games. The Pirate's Guide is in {orientation}.",
    ],
    "gangplank_reminder": [
        "Ahoy, {member}! A friendly nudge from your butler: introduce yourself here and tell us your favorite "
        "game, and a Harbormaster will wave you aboard. The gangplank goes up {deadline}.",
        "{member}, the crew's still waiting to meet you! Say hello here and tell us your favorite game. "
        "If I don't hear from you, the gangplank goes up {deadline}.",
    ],
    "gangplank_kick_dm": [
        "Ahoy from {server}! You didn't introduce yourself within {days} days, so I've had to raise the "
        "gangplank. No hard feelings: you're welcome back with a fresh invite whenever you're ready.",
    ],
    "colours_prompt": [
        "Pick your {title} below and I'll see to the rest!",
        "At your service! Tick whichever {title} suit you and press away.",
    ],
    "colours_done": [
        "All sorted! {changes}",
        "Done and dusted! {changes}",
    ],
    "colours_same": [
        "Nothing to change: you're already wearing exactly those!",
    ],
    "colours_gone": [
        "{cuss} That menu has been taken down. A Quartermaster can post a fresh one.",
    ],
    "colours_cant": [
        "{cuss} I couldn't change your roles. A Quartermaster needs to move my role above these ones.",
    ],
    "colours_zone_prompt": [
        "Your region covers a lot of ocean! Which of these is closest to you? It's how I show every time in "
        "your own time zone.",
    ],
    "follow_prompt": [
        "Which games shall I keep you posted on? You'll get each game's ping role and I'll add you to its "
        "thread in {forum}.",
    ],
    "follow_done": [
        "Crow's nest updated! {changes}",
    ],
    "shipslog_intro": [
        "Ahoy, Fortress! Your butler has polished the log book. Here's the week that was, and the week to come.",
        "Another week on the high seas! I've tallied the crews, counted the cake and charted what's next.",
        "Gather round the grog barrel! Here's what the Fortress got up to this week.",
    ],
    "shipslog_quiet": [
        "A calm week on the water: no crews, voyages or birthdays to report. Perfect weather for planning "
        "the next one! Try `/voyage create`.",
    ],
    "crowsnest_post": [
        "Land ho! Fresh news for {game}:",
        "From the crow's nest: news about {game}!",
    ],
    "parley_hello": [
        "Ahoy! You rang? Ask me anything: voyages, crews, games, the rules, or the wider seas.",
        "PlunderBot at your service! What can your butler fetch for you?",
    ],
    "parley_tired": [
        "{cuss} My voice box needs a rest: that's your {daily} chats for today. Slash commands still work, and "
        "I'll be all ears again tomorrow!",
    ],
    "parley_broke": [
        "{cuss} The grog budget for chatting is spent until next month! Slash commands still work in the meantime.",
    ],
    "parley_error": [
        "{cuss} My gears jammed trying to answer that. Try again in a moment?",
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
