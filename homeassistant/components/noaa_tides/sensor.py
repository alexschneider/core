"""Support for the NOAA Tides and Currents API."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any, Literal, TypedDict

from dateutil import parser
import requests
import voluptuous as vol

from homeassistant.components.sensor import (
    PLATFORM_SCHEMA as SENSOR_PLATFORM_SCHEMA,
    SensorEntity,
)
from homeassistant.const import CONF_NAME, CONF_TIME_ZONE, CONF_UNIT_SYSTEM
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util.unit_system import METRIC_SYSTEM

_LOGGER = logging.getLogger(__name__)

CONF_STATION_ID = "station_id"

DEFAULT_NAME = "NOAA Tides"
DEFAULT_TIMEZONE = "lst_ldt"

SCAN_INTERVAL = timedelta(minutes=60)

TIMEZONES = ["gmt", "lst", "lst_ldt"]
UNIT_SYSTEMS = ["english", "metric"]

DATA_GETTER_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

PLATFORM_SCHEMA = SENSOR_PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_STATION_ID): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_TIME_ZONE, default=DEFAULT_TIMEZONE): vol.In(TIMEZONES),
        vol.Optional(CONF_UNIT_SYSTEM): vol.In(UNIT_SYSTEMS),
    }
)


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the NOAA Tides and Currents sensor."""
    station_id = config[CONF_STATION_ID]
    name = config.get(CONF_NAME)
    timezone = config.get(CONF_TIME_ZONE)

    if CONF_UNIT_SYSTEM in config:
        unit_system = config[CONF_UNIT_SYSTEM]
    elif hass.config.units is METRIC_SYSTEM:
        unit_system = UNIT_SYSTEMS[1]
    else:
        unit_system = UNIT_SYSTEMS[0]

    noaa_sensor = NOAATidesAndCurrentsSensor(name, station_id, timezone, unit_system)

    add_entities([noaa_sensor], True)


class NOAATidesData(TypedDict):
    """Representation of a single tide."""

    time_stamp: datetime
    hi_lo: Literal["L", "H"]
    predicted_wl: float


class NOAATidesAndCurrentsSensor(SensorEntity):
    """Representation of a NOAA Tides and Currents sensor."""

    _attr_attribution = "Data provided by NOAA"

    def __init__(self, name, station_id, timezone, unit_system) -> None:
        """Initialize the sensor."""
        self._name = name
        self._station_id = station_id
        self._timezone = timezone
        self._unit_system = unit_system
        self.data: list[NOAATidesData] | None = None

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return self._name

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes of this device."""
        attr: dict[str, Any] = {}
        if self.data is None:
            return attr
        if self.data[1]["hi_lo"] == "H":
            attr["high_tide_time"] = self.data[1]["time_stamp"].strftime(
                "%Y-%m-%dT%H:%M"
            )
            attr["high_tide_height"] = self.data[1]["predicted_wl"]
            attr["low_tide_time"] = self.data[2]["time_stamp"].strftime(
                "%Y-%m-%dT%H:%M"
            )
            attr["low_tide_height"] = self.data[2]["predicted_wl"]
        elif self.data[1]["hi_lo"] == "L":
            attr["low_tide_time"] = self.data[1]["time_stamp"].strftime(
                "%Y-%m-%dT%H:%M"
            )
            attr["low_tide_height"] = self.data[1]["predicted_wl"]
            attr["high_tide_time"] = self.data[2]["time_stamp"].strftime(
                "%Y-%m-%dT%H:%M"
            )
            attr["high_tide_height"] = self.data[2]["predicted_wl"]
        return attr

    @property
    def native_value(self):
        """Return the state of the device."""
        if self.data is None:
            return None
        api_time = self.data[0]["time_stamp"]
        if self.data[0]["hi_lo"] == "H":
            tidetime = api_time.strftime("%-I:%M %p")
            return f"High tide at {tidetime}"
        if self.data[0]["hi_lo"] == "L":
            tidetime = api_time.strftime("%-I:%M %p")
            return f"Low tide at {tidetime}"
        return None

    def update(self) -> None:
        """Get the latest data from NOAA Tides and Currents API."""
        begin = datetime.now()
        delta = timedelta(days=2)
        end = begin + delta
        try:
            params = {
                "begin_date": begin.strftime("%Y%m%d %H:%M"),
                "end_date": end.strftime("%Y%m%d %H:%M"),
                "product": "predictions",
                "datum": "MLLW",
                "interval": "hilo",
                "units": self._unit_system,
                "time_zone": self._timezone,
                "format": "json",
                "station": self._station_id,
            }
            response = requests.get(DATA_GETTER_URL, params=params, timeout=10)
            api_data = response.json()["predictions"]
            self.data = [
                NOAATidesData(
                    time_stamp=parser.parse(tide_data["t"]),
                    hi_lo=tide_data["type"],
                    predicted_wl=tide_data["v"],
                )
                for tide_data in api_data
            ]
            _LOGGER.debug("Data = %s", api_data)
            _LOGGER.debug(
                "Recent Tide data queried with start time set to %s",
                begin.strftime("%m-%d-%Y %H:%M"),
            )
        except ValueError as err:
            _LOGGER.error("Check NOAA Tides and Currents: %s", err.args)
            self.data = None
        except requests.exceptions.RequestException as err:
            _LOGGER.error("Error fetching NOAA Tides and Currents data: %s", err)
            self.data = None
