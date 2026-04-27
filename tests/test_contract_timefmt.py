from datetime import datetime, timezone

from caden.util.timefmt import format_display_time, to_12hr


def test_to_12hr_rewrites_only_unambiguous_24_hour_times():
    text = "Calendar says 14:30, 00:15, 9:30, and 2:30 PM."

    rendered = to_12hr(text)

    assert "2:30 PM" in rendered
    assert "12:15 AM" in rendered
    assert "9:30" in rendered
    assert rendered.count("2:30 PM") == 2


def test_to_12hr_is_idempotent():
    text = "Start at 18:45 and end at 20:00."

    once = to_12hr(text)
    twice = to_12hr(once)

    assert once == twice


def test_format_display_time_uses_detroit_12_hour_time_by_default():
    when = datetime(2026, 4, 27, 3, 30, tzinfo=timezone.utc)

    rendered = format_display_time(when)

    assert rendered == "11:30 pm"


def test_format_display_time_can_include_weekday_in_detroit_timezone():
    when = datetime(2026, 4, 27, 3, 30, tzinfo=timezone.utc)

    rendered = format_display_time(when, include_weekday=True)

    assert rendered == "sun 11:30 pm"