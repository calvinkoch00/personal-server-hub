def get_help_message() -> str:
    from personal_server_hub.adapters.discord.formatter import format_message

    return format_message("help")
