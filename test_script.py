import asyncio

async def main():
    from caden.main import _boot
    from caden.ui.app import CadenApp
    from caden.ui.dashboard import SidePanel
    from caden.ui.chat import ChatWidget
    from textual.widgets import Button, Static

    services = _boot()
    app = CadenApp(services)

    # Run a quick render probe for manual debugging.
    async with app.run_test(size=(120, 40)):
        # Wait briefly for initialization/rendering
        await asyncio.sleep(2)

        clock = app.query_one("#app-clock", Static).render().plain
        add_task_btn = app.query_one("#add-task", Button).label.plain
        panels = list(app.query(SidePanel))
        today_title = panels[0].query_one("#title", Static).render().plain
        next_7_title = panels[1].query_one("#title", Static).render().plain
        chat_header = app.query_one(ChatWidget).query_one("#chat-header", Static).render().plain

        print(f"CLOCK: {clock}")
        print(f"ADD_TASK: {add_task_btn}")
        print(f"TODAY: {today_title}")
        print(f"NEXT_7: {next_7_title}")
        print(f"CHAT_HEADER: {chat_header}")

    services.close()

if __name__ == "__main__":
    asyncio.run(main())
