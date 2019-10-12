"""Constants for tauron."""
DOMAIN = "ais_tauron"
DEFAULT_NAME = "Tauron AmiPlus"
DATA_TAURON_CLIENT = "data_client"
CONF_METER_ID = "energy_meter_id"
CONF_URL_SERVICE = "https://elicznik.tauron-dystrybucja.pl"
CONF_URL_LOGIN = "https://logowanie.tauron-dystrybucja.pl/login"
CONF_URL_CHARTS = "https://elicznik.tauron-dystrybucja.pl/index/charts"
CONF_REQUEST_HEADERS = {"cache-control": "no-cache"}
CONF_REQUEST_PAYLOAD_CHARTS = {"dane[cache]": 0}
TYPE_ZONE = "zone"
TYPE_CONSUMPTION_DAILY = "consumption_daily"
TYPE_CONSUMPTION_MONTHLY = "consumption_monthly"
TYPE_CONSUMPTION_YEARLY = "consumption_yearly"
TARIFF_G12 = "G12"