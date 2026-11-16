"""Application credentials platform for Advanced Google Calendar."""

from homeassistant.components.application_credentials import AuthorizationServer
from homeassistant.core import HomeAssistant

from .const import OAUTH2_AUTHORIZE, OAUTH2_TOKEN


async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    """Return the Google authorization server."""
    return AuthorizationServer(authorize_url=OAUTH2_AUTHORIZE, token_url=OAUTH2_TOKEN)


async def async_get_description_placeholders(hass: HomeAssistant) -> dict[str, str]:
    """Return description placeholders for the credentials dialog."""
    return {
        "console_url": "https://console.cloud.google.com/auth/clients",
        "redirect_url": "https://my.home-assistant.io/redirect/oauth",
        "more_info_url": "https://github.com/gbasedow/advanced_google_calendar/blob/main/docs/ANLEITUNG.md",
    }
