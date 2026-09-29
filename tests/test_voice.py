import random
import string

import pytest

from plunderbot import voice


@pytest.mark.parametrize("key", sorted(voice.LINES))
def test_every_line_fills_in(key):
    # Every placeholder any line might use, so a typo'd field fails here, not in Discord.
    values = dict(version="1.2.3", date="May 4", month_name="February", day=30, names="@Twiddles",
                  captain="@Boxer", game="Sea of Thieves", size="Galleon", role="@SoT", channel="#voice",
                  options="Sloop, Galleon")
    fields = {f for line in voice.LINES[key] for _, f, _, _ in string.Formatter().parse(line) if f}
    assert fields <= set(values) | {"cuss"}, f"{key} uses unknown fields: {fields - set(values)}"
    for i in range(len(voice.LINES[key]) * 4):
        text = voice.say(key, rng=random.Random(i), **values)
        assert text and "{" not in text
        assert len(text) <= 2000  # Discord's message limit


def test_join_names():
    assert voice.join_names(["A"]) == "A"
    assert voice.join_names(["A", "B"]) == "A and B"
    assert voice.join_names(["A", "B", "C"]) == "A, B and C"


def test_no_real_swears():
    banned = {"fuck", "shit", "damn", "bitch", "ass "}
    everything = " ".join(voice.CUSSES + [line for lines in voice.LINES.values() for line in lines]).lower()
    assert not any(word in everything for word in banned)
