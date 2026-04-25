from datetime import datetime
from caden.ui.add_task import rewrite_times_local, _format_block_line

local_tz = datetime.now().astimezone().tzinfo

samples = [
    "I will start at 21:00 and end at 22:30.",
    "Block runs 2026-04-25 21:00 → 2026-04-25 22:30.",
    "ISO with offset: 2026-04-26T01:00:00Z is the boundary.",
    "Already pretty: 9 PM works for me, also 9:30pm and 12 a.m.",
    "Edge case 00:00 should be left alone.",
    "Mixed: 2026-04-25T21:00:00-04:00 and bare 7:15 inside one line.",
]
for s in samples:
    print(f"IN : {s}")
    print(f"OUT: {rewrite_times_local(s, local_tz)}")
    print()

# Block formatting
start = datetime(2026, 4, 25, 21, 0, tzinfo=local_tz)
end = datetime(2026, 4, 25, 22, 30, tzinfo=local_tz)
print(f"BLOCK today: {_format_block_line(start, end, local_tz)}")
start2 = datetime(2026, 4, 26, 9, 0, tzinfo=local_tz)
end2 = datetime(2026, 4, 26, 10, 0, tzinfo=local_tz)
print(f"BLOCK tomorrow: {_format_block_line(start2, end2, local_tz)}")
start3 = datetime(2026, 5, 3, 14, 0, tzinfo=local_tz)
end3 = datetime(2026, 5, 3, 15, 0, tzinfo=local_tz)
print(f"BLOCK other: {_format_block_line(start3, end3, local_tz)}")
