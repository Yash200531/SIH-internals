"""Device registration for kiosk/tablet devices."""
import time
from dataclasses import dataclass
from uuid import UUID


@dataclass
class Device:
    device_id: str  # hardware ID or generated
    facility_id: UUID
    device_type: str  # "kiosk", "tablet", "desktop"
    device_name: str
    is_active: bool
    registered_at: float
    last_seen_at: float
    metadata: dict


_devices: dict[str, Device] = {}


def register_device(device_id: str, facility_id: UUID, device_type: str, device_name: str) -> Device:
    """Register a new device."""
    device = Device(
        device_id=device_id,
        facility_id=facility_id,
        device_type=device_type,
        device_name=device_name,
        is_active=True,
        registered_at=time.time(),
        last_seen_at=time.time(),
        metadata={},
    )
    _devices[device_id] = device
    return device


def get_device(device_id: str) -> Device | None:
    return _devices.get(device_id)


def deactivate_device(device_id: str) -> bool:
    device = _devices.get(device_id)
    if device:
        device.is_active = False
        return True
    return False
