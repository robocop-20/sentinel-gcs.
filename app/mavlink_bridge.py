import os
import logging
import time
import requests
from pymavlink import mavutil
from .config import get_settings
from .observability import configure_logging
from .service_health import ServiceHealth
from .service_auth import ServiceTokenProvider


LOGGER = logging.getLogger(__name__)


GPS_FIX_NAMES = {
    0: "NO_GPS",
    1: "NO_FIX",
    2: "2D",
    3: "3D",
    4: "DGPS",
    5: "RTK_FLOAT",
    6: "RTK_FIXED",
}


def mavlink_enum_name(group: str, value: int) -> str | None:
    entry = mavutil.mavlink.enums.get(group, {}).get(value)
    return str(entry.name) if entry is not None else None


def main():
    settings = get_settings()
    settings.validate()
    configure_logging("sentinel-telemetry", settings.log_level)
    health = ServiceHealth("sentinel-telemetry", settings.service_health_port)
    health.start()
    api_url = os.getenv("API_URL", "http://localhost:8080")
    token_provider = ServiceTokenProvider(
        api_url,
        settings.service_client_id,
        settings.service_client_secret_file,
        ca_cert=settings.service_ca_cert,
        client_cert=settings.service_client_cert,
        client_key=settings.service_client_key,
    )
    session = requests.Session()
    token_provider.configure_session(session)
    serial_options = (
        {"baud": settings.mavlink_baud}
        if settings.mavlink_endpoint.upper().startswith("COM")
        else {}
    )
    connection = mavutil.mavlink_connection(settings.mavlink_endpoint, **serial_options)
    connection.wait_heartbeat()
    health.set_ready(True, link="mavlink", api_delivery="pending")
    LOGGER.info(
        "MAVLink heartbeat received",
        extra={"event": "mavlink_connected", "component": "telemetry"},
    )
    latest_by_vehicle: dict[str, dict] = {}

    def post_telemetry(latest: dict):
        if not {"latitude", "longitude", "altitude_m", "heading_deg"}.issubset(latest):
            return
        latest["timestamp"] = time.time()
        latest["source"] = "mavlink"
        try:
            session.post(
                f"{api_url}/api/telemetry",
                json=latest,
                headers=token_provider.authorization_header(),
                timeout=2,
            ).raise_for_status()
            health.set_ready(True, link="mavlink", api_delivery="healthy")
        except requests.RequestException as exc:
            health.set_ready(
                False, reason="api_delivery_failed", error_type=type(exc).__name__
            )
            LOGGER.warning(
                "Telemetry delivery failed",
                extra={"event": "delivery_failed", "component": "telemetry"},
            )

    while True:
        message = connection.recv_match(
            type=[
                "HEARTBEAT",
                "GPS_RAW_INT",
                "GLOBAL_POSITION_INT",
                "ATTITUDE",
                "DISTANCE_SENSOR",
                "SYS_STATUS",
                "RADIO_STATUS",
            ],
            blocking=True,
        )
        if message is None:
            continue
        system_id = int(message.get_srcSystem())
        component_id = int(message.get_srcComponent())
        vehicle_id = f"mavlink-{system_id}"
        latest = latest_by_vehicle.setdefault(
            vehicle_id,
            {
                "vehicle_id": vehicle_id,
                "system_id": system_id,
                "component_id": component_id,
                "source": "mavlink",
            },
        )
        latest["component_id"] = component_id
        message_type = message.get_type()
        if message_type == "HEARTBEAT":
            latest.update(
                {
                    "vehicle_type": mavlink_enum_name("MAV_TYPE", int(message.type)),
                    "flight_mode": mavutil.mode_string_v10(message),
                    "armed": bool(
                        int(message.base_mode)
                        & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
                    ),
                }
            )
            post_telemetry(latest)
        elif message_type == "GPS_RAW_INT":
            fix_type = int(message.fix_type)
            latest.update(
                {
                    "gps_fix": GPS_FIX_NAMES.get(fix_type, "NO_FIX"),
                    "satellites_visible": int(message.satellites_visible)
                    if int(message.satellites_visible) != 255
                    else None,
                    "hdop": float(message.eph) / 100
                    if int(message.eph) != 65535
                    else None,
                    "vdop": float(message.epv) / 100
                    if int(message.epv) != 65535
                    else None,
                }
            )
            post_telemetry(latest)
        elif message_type == "GLOBAL_POSITION_INT":
            latest.update(
                {
                    "latitude": message.lat / 1e7,
                    "longitude": message.lon / 1e7,
                    "altitude_m": max(message.relative_alt / 1000, 0),
                    "relative_altitude_m": message.relative_alt / 1000,
                    "heading_deg": (message.hdg / 100) % 360,
                    "ground_speed_mps": ((message.vx**2 + message.vy**2) ** 0.5) / 100,
                    "vertical_speed_mps": -message.vz / 100,
                }
            )
            post_telemetry(latest)
        elif message_type == "ATTITUDE":
            latest.update(
                {
                    "roll_deg": message.roll * 57.2957795,
                    "pitch_deg": message.pitch * 57.2957795,
                    "heading_deg": (message.yaw * 57.2957795) % 360,
                    "attitude_valid": True,
                }
            )
            post_telemetry(latest)
        elif message_type == "DISTANCE_SENSOR":
            distance = message.current_distance / 100
            if distance <= 0:
                continue
            payload = {
                "timestamp": time.time(),
                "vehicle_id": vehicle_id,
                "distance_m": distance,
                "min_distance_m": message.min_distance / 100,
                "max_distance_m": message.max_distance / 100,
                "orientation": settings.lidar_orientation,
                "source": "mavlink_lidar",
            }
            try:
                session.post(
                    f"{api_url}/api/range",
                    json=payload,
                    headers=token_provider.authorization_header(),
                    timeout=2,
                ).raise_for_status()
                health.set_ready(True, link="mavlink", api_delivery="healthy")
            except requests.RequestException as exc:
                health.set_ready(
                    False, reason="api_delivery_failed", error_type=type(exc).__name__
                )
                LOGGER.warning(
                    "Range delivery failed",
                    extra={"event": "delivery_failed", "component": "range"},
                )
        elif message_type == "SYS_STATUS" and message.battery_remaining >= 0:
            latest["battery_percent"] = message.battery_remaining
            if int(message.voltage_battery) != 65535:
                latest["battery_voltage_v"] = message.voltage_battery / 1000
            if int(message.current_battery) != -1:
                latest["battery_current_a"] = message.current_battery / 100
        elif message_type == "RADIO_STATUS" and message.rssi != 255:
            latest["link_quality_percent"] = round(message.rssi / 255 * 100, 1)


if __name__ == "__main__":
    main()
