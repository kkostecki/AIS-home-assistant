"""
Support for AIS WiFI connection.

For more details about this platform, please refer to the documentation at
https://sviete.github.io/AIS-docs
"""
import logging
import asyncio
from .config_flow import configured_service


_LOGGER = logging.getLogger(__name__)

@asyncio.coroutine
def async_setup(hass, config):
    """Set up the AIS WiFI connection."""
    _LOGGER.info("async_setup AIS WiFI connection .")