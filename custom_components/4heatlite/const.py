"""Constants for the 4HEAT Lite integration."""

DOMAIN = "4heatlite"
DATA_COORDINATOR = "coordinator"

TCP_PORT = 80
SOCKET_TIMEOUT = 5
SOCKET_BUFFER = 1024

QUERY_SENSORS = '["2WC","1","0310"]'
QUERY_CONFIG = {
    "target_temp": '["2WC","1","0312005a"]',
    "power": '["2WC","1","030e016c"]',
}

DEFAULT_SCAN_INTERVAL = 30

STATE_NAMES = {
    0: "OFF",
    1: "Check Up",
    2: "Ignition",
    3: "Stabilization",
    4: "Ignition",
    5: "Run",
    6: "Modulation",
    7: "Extinguishing",
    8: "Safety",
    9: "Block",
    10: "Recover Ignition",
    11: "Standby",
    13: "Run M",
    30: "Ignition",
    31: "Ignition",
    32: "Ignition",
    33: "Ignition",
    34: "Ignition",
}

ERROR_NAMES = {
    0: "None",
    1: "Safety Thermostat HV1",
    2: "Safety PressureSwitch HV2",
    3: "Exhaust Temp lowering",
    4: "Water over Temperature",
    5: "Exhaust over Temperature",
    6: "Unknown",
    7: "Encoder: No Signal",
    8: "Encoder: Fan regulation failed",
    9: "Low boiler pressure",
    10: "High boiler pressure",
    11: "Clock reset (power loss)",
    12: "Failed Ignition",
    13: "Ignition error",
    14: "Ignition error",
    15: "Lack of Voltage",
    16: "Ignition error",
    17: "Ignition error",
    18: "Lack of Voltage",
    44: "Door error",
}

# Proxy configuration
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_KEY = "device_key"
CONF_MODULE_ADDRESS = "module_address"
CONF_PROXY_MODE = "proxy_mode"
CONF_SCHEDULE_ENABLED = "schedule_enabled"  # v2 migration only
CONF_CACHED_SCHEDULE = "cached_schedule"  # v2 migration only
CONF_ACTIVE_SCHEDULE = "active_schedule"
CONF_CACHED_SCHEDULES = "cached_schedules"
NUM_SCHEDULE_SLOTS = 3
PROXY_MODE_DIRECT = "direct"
PROXY_MODE_LOCAL = "local_only"
PROXY_MODE_KEEPALIVE = "cloud_keepalive"

AZURE_HTTPS_BASE = "https://wifi4heat.azurewebsites.net"
CONF_PROXY_LOG_LEVEL = "proxy_log_level"
CONF_PROXY_DEBUG = "proxy_debug"  # v0.9.92 migration only
LOG_LEVEL_WARNING = "warning"
LOG_LEVEL_INFO = "info"
LOG_LEVEL_DEBUG = "debug"
PROXY_POLL_INTERVAL = 120

STORE_REGISTERS = {
    "12ffff": {"key": "exhaust_temp_store", "group": "12", "scale": 1},
    "12fff7": {"key": "room_temp_store", "group": "12", "scale": 0.1},
    "12ffe0": {"key": "remote_room_temp", "group": "12", "scale": 0.1},
    "12ffe8": {"key": "remote_room_temp_2", "group": "12", "scale": 0.1},
    "12ffed": {"key": "airflow", "group": "12", "scale": 1},
    "12ffde": {"key": "cleaning_counter", "group": "12", "scale": 1},
    "12ffdf": {"key": "service_counter", "group": "12", "scale": 1},
    "12005a": {"key": "target_temp", "group": "12", "scale": 0.1},
    "120058": {"key": "reg_120058", "group": "12", "scale": 1},
    "120059": {"key": "reg_120059", "group": "12", "scale": 1},
    "0e016c": {"key": "power", "group": "0e"},
    "0e023f": {"key": "heating_fan_power", "group": "0e"},
    "0e0266": {"key": "ducted_fan_1", "group": "0e"},
    "0e027e": {"key": "ducted_fan_2", "group": "0e"},
    "0e0231": {"key": "reg_0e0231", "group": "0e"},
    "0c81": {"key": "module_info", "group": "0c"},
}

# Schedule constants
QUERY_SCHEDULE = '["CCG","0"]'
MINUTES_PER_DAY = 1440
DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_OFFSETS = {name: i * MINUTES_PER_DAY for i, name in enumerate(DAY_NAMES)}
BAND_NAMES = ["off", "eco", "comfort", "comfort2"]
TEMP_SCALE = 10
SERVICE_GET_SCHEDULE = "get_schedule"
SERVICE_SET_SCHEDULE = "set_schedule"

# Write command constants
WRITE_FUNCTION = "05"
REGISTER_TEMP = "12005a"
REGISTER_POWER = "0e016c"
TEMP_MIN_RAW = 0x0064
TEMP_MAX_RAW = 0x0190
TEMP_WRITE_SUFFIX = "0001000100"
