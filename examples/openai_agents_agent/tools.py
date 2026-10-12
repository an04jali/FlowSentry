from agents import RunContextWrapper, function_tool


@function_tool(
    name_override="weather_lookup",
    description_override="Get current weather for a city.",
    use_docstring_info=True,
)
def get_weather(city: str, units: str = "metric") -> dict:
    """Return weather data for a city."""
    return {"city": city, "units": units}


@function_tool(defer_loading=True)
async def lookup_user(ctx: RunContextWrapper, user_id: str) -> str:
    """Look up an internal user profile."""
    return user_id
