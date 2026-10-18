"""hermes-daily-reading: a daily reading digest from RSS/Atom feeds for Hermes Agent."""

from __future__ import annotations

BLUEPRINT_PROMPT = (
    "Call the daily_reading_run tool once, with no arguments, and reply with its message exactly as returned. "
    "Do not call other tools."
)


def register(ctx) -> None:
    from . import dr_digest
    from .dr_cli import make_handler, setup_parser
    from .dr_host import model_call, settings_from_ctx, tool_dispatch
    from .dr_tools import FEEDS_SCHEMA, RUN_SCHEMA, make_tool_handlers

    def settings():
        return settings_from_ctx(ctx)

    def run(current_settings, force: bool):
        llm = getattr(ctx, "llm", None)
        return dr_digest.run(current_settings, force=force,
                             call_model=model_call(llm) if llm is not None else None,
                             dispatch=tool_dispatch(getattr(ctx, "dispatch_tool", None)))

    run_handler, feeds_handler = make_tool_handlers(settings, run)
    ctx.register_tool(name="daily_reading_run", toolset="daily-reading", schema=RUN_SCHEMA, handler=run_handler,
                      description="Build today's daily reading digest", emoji="📰")
    ctx.register_tool(name="daily_reading_feeds", toolset="daily-reading", schema=FEEDS_SCHEMA,
                      handler=feeds_handler, description="List or edit the daily reading feeds", emoji="📰")
    ctx.register_cli_command(
        name="reading", help="Daily reading digest: run, status, feeds", setup_fn=setup_parser,
        handler_fn=make_handler(settings, run, dr_digest.status),
        description="Build the daily reading digest and manage its feeds.")
    register_blueprint = getattr(ctx, "register_automation_blueprint", None)
    if register_blueprint is not None:
        register_blueprint(
            "daily", title="Daily reading",
            description="Build the daily reading digest (feeds ranked by your themes, summary and audio) every day.",
            category="reading", schedule_template="{minute} {hour} * * *", prompt_template=BLUEPRINT_PROMPT,
            slots=[{"name": "time", "type": "time", "label": "What time?", "default": "07:00"},
                   {"name": "deliver", "type": "enum", "label": "Where should the result go?", "default": "local",
                    "options": ["local", "origin"], "strict": False}],
            deliver_default="local", tags=["reading", "rss"])
