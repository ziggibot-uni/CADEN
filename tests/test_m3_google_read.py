import pytest
from datetime import datetime, timezone

from caden.ui.app import CadenApp
from caden.google_sync.calendar import CalendarEvent
from caden.ui.dashboard import Dashboard

@pytest.mark.asyncio
async def test_m3_google_read(mock_services):
    class MockCalendar:
        def list_window(self, start, end):
            return [
                CalendarEvent(
                    id="event1",
                    summary="Test Event Today",
                    start=datetime(2026, 4, 30, 20, 0, tzinfo=timezone.utc), # Make sure it's in the future
                    end=datetime(2026, 4, 30, 23, 0, tzinfo=timezone.utc),
                    raw={}
                )
            ]
            
    mock_services.calendar = MockCalendar()
    
    app = CadenApp(mock_services)
    async with app.run_test() as pilot:
        # Give Dashboard time to fetch and render
        await pilot.pause(0.5)
        
        # Test Event Today should be inside the layout's textual body
        from caden.ui.dashboard import TaskItem
        items = list(app.query(TaskItem))
        
        text = " ".join([str(item._text) for item in items])
        assert "Test Event Today" in text, f"Mocked event not rendered on main dashboard. Items available: {text}"
