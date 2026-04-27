import asyncio
from caden.main import _boot
from caden.app import CadenApp
from caden.test_utils import run_test

async def main():
    m3, calendar, chat, agent = _boot()
    app = CadenApp(m3=m3, calendar=calendar, chat=chat, agent=agent)
    async with run_test(app, size=(120, 40)):
        await asyncio.sleep(1)
        for widget in app.walk_all():
             if widget.id:
                 print(f"ID: {widget.id} | Class: {type(widget).__name__}")
        
        # Try to find specific text if IDs are missing
        for widget in app.walk_all():
            try:
                text = ""
                if hasattr(widget, "renderable") and hasattr(widget.renderable, "plain"):
                    text = widget.renderable.plain
                elif hasattr(widget, "label") and hasattr(widget.label, "plain"):
                    text = widget.label.plain
                
                if text and ("Today" in text or "Next 7" in text or "Task" in text):
                    print(f"POSSIBLE: ID={widget.id} Text={text}")
            except:
                pass

if __name__ == "__main__":
    asyncio.run(main())
