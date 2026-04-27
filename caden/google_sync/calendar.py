"""Google Calendar client. Read events + create/update events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..errors import GoogleSyncError


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    summary: str
    start: datetime
    end: datetime
    raw: dict


class CalendarClient:
    def __init__(
        self,
        credentials,
        calendar_id: str = "primary",
        *,
        readable_calendar_ids: tuple[str, ...] | None = None,
        writable_calendar_id: str | None = None,
    ) -> None:
        try:
            self.service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        except Exception as e:
            raise GoogleSyncError(f"failed to build Calendar service: {e}") from e
        self.readable_calendar_ids = readable_calendar_ids or (calendar_id,)
        self.writable_calendar_id = writable_calendar_id or calendar_id
        self.calendar_id = self.writable_calendar_id

    def list_window(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        out: list[CalendarEvent] = []
        for calendar_id in self.readable_calendar_ids:
            try:
                resp = (
                    self.service.events()
                    .list(
                        calendarId=calendar_id,
                        timeMin=start.astimezone(timezone.utc).isoformat(),
                        timeMax=end.astimezone(timezone.utc).isoformat(),
                        singleEvents=True,
                        orderBy="startTime",
                        maxResults=250,
                    )
                    .execute()
                )
            except HttpError as e:
                raise GoogleSyncError(f"Calendar list failed: {e}") from e

            for item in resp.get("items", []):
                s = _parse_time(item.get("start") or {})
                e = _parse_time(item.get("end") or {})
                if s is None or e is None:
                    continue
                out.append(
                    CalendarEvent(
                        id=item["id"],
                        summary=item.get("summary") or "(no title)",
                        start=s,
                        end=e,
                        raw=item,
                    )
                )
        out.sort(key=lambda ev: ev.start)
        return out

    def create_event(
        self,
        summary: str,
        start: datetime,
        end: datetime,
        description: str = "",
    ) -> CalendarEvent:
        body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start.astimezone(timezone.utc).isoformat()},
            "end": {"dateTime": end.astimezone(timezone.utc).isoformat()},
        }
        try:
            created = (
                self.service.events()
                .insert(calendarId=self.writable_calendar_id, body=body)
                .execute()
            )
        except HttpError as e:
            raise GoogleSyncError(f"Calendar insert failed: {e}") from e
        return CalendarEvent(
            id=created["id"],
            summary=created.get("summary") or summary,
            start=start,
            end=end,
            raw=created,
        )

    def set_end_time(self, event_id: str, new_end: datetime) -> None:
        """Truncate a paired event's end to new_end, e.g. when a task completes early."""
        try:
            self.service.events().patch(
                calendarId=self.writable_calendar_id,
                eventId=event_id,
                body={"end": {"dateTime": new_end.astimezone(timezone.utc).isoformat()}},
            ).execute()
        except HttpError as e:
            if e.resp.status in (404, 410):
                return
            raise GoogleSyncError(f"Calendar patch failed for {event_id}: {e}") from e

    def reschedule(
        self, event_id: str, new_start: datetime, new_end: datetime
    ) -> None:
        """Move a CADEN-owned event to a new time window."""
        try:
            self.service.events().patch(
                calendarId=self.writable_calendar_id,
                eventId=event_id,
                body={
                    "start": {"dateTime": new_start.astimezone(timezone.utc).isoformat()},
                    "end": {"dateTime": new_end.astimezone(timezone.utc).isoformat()},
                },
            ).execute()
        except HttpError as e:
            if e.resp.status in (404, 410):
                return
            raise GoogleSyncError(
                f"Calendar reschedule failed for {event_id}: {e}"
            ) from e


def _parse_time(obj: dict) -> datetime | None:
    s = obj.get("dateTime") or obj.get("date")
    if not s:
        return None
    try:
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        # all-day event: treat as UTC midnight
        d = datetime.fromisoformat(s)
        return d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
