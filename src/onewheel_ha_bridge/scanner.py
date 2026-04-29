from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import ipaddress
import logging
import re
from collections.abc import Callable

from .config import VescConfig, VescDiscoveryConfig
from .models import FirmwareInfo
from .protocol import COMM_FW_VERSION, VescTcpClient

LOG = logging.getLogger(__name__)

HARD_MAX_HOSTS_PER_SCAN = 1024
HARD_MAX_PORTS_PER_SCAN = 16
HARD_MAX_PROBES_PER_SCAN = 2048
HARD_MAX_WORKERS = 64


@dataclass(frozen=True, slots=True)
class VescTcpEndpoint:
    host: str
    port: int
    firmware: FirmwareInfo

    @property
    def key(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def identity_key(self) -> str:
        uuid = (self.firmware.uuid or "").lower()
        if uuid and uuid != "0" * len(uuid):
            return f"uuid:{uuid}"
        return f"endpoint:{self.key}"


def slugify(value: str, fallback: str = "vesc") -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or fallback


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def board_id_for_endpoint(endpoint: VescTcpEndpoint) -> str:
    uuid = (endpoint.firmware.uuid or "").lower()
    if uuid and uuid != "0" * len(uuid):
        return f"vesc_{uuid}"
    return f"{slugify(f'vesc_{endpoint.host}_{endpoint.port}')}_{_short_hash(endpoint.key)}"


def _hosts_from_network(cidr: str, max_hosts: int, min_ipv4_prefix_length: int, allow_public_networks: bool) -> list[str]:
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except ValueError as exc:
        raise ValueError(f"invalid discovery network {cidr!r}: {exc}") from exc
    if network.version != 4:
        raise ValueError(f"discovery network {cidr!r} is not IPv4")
    if network.prefixlen < min_ipv4_prefix_length:
        raise ValueError(
            f"discovery network {cidr!r} is broader than allowed /{min_ipv4_prefix_length}; "
            "use explicit hosts or lower min_ipv4_prefix_length deliberately"
        )
    if not allow_public_networks and not network.is_private:
        raise ValueError(f"discovery network {cidr!r} is public; set allow_public_networks only if you really mean it")
    hosts: list[str] = []
    for address in network.hosts():
        hosts.append(str(address))
        if len(hosts) >= max_hosts:
            break
    return hosts


def iter_discovery_hosts(config: VescDiscoveryConfig, configured_host: str | None = None) -> list[str]:
    hosts: list[str] = []
    seen: set[str] = set()

    max_hosts = max(0, min(config.max_hosts_per_scan, HARD_MAX_HOSTS_PER_SCAN))

    def add(host: str) -> None:
        if len(hosts) >= max_hosts:
            return
        if host in seen:
            return
        hosts.append(host)
        seen.add(host)

    if config.include_configured_host and configured_host:
        add(configured_host)
    for host in config.hosts:
        add(host)
    for network in config.networks:
        if len(hosts) >= max_hosts:
            break
        for host in _hosts_from_network(network, max_hosts, config.min_ipv4_prefix_length, config.allow_public_networks):
            add(host)
            if len(hosts) >= max_hosts:
                break
    return hosts


def probe_vesc_tcp(host: str, port: int, base_config: VescConfig, timeout_seconds: float) -> VescTcpEndpoint | None:
    probe_config = VescConfig(
        host=host,
        port=port,
        thor_can_id=base_config.thor_can_id,
        bms_can_id=base_config.bms_can_id,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=base_config.poll_interval_seconds,
        static_refresh_every_polls=base_config.static_refresh_every_polls,
    )
    client = VescTcpClient(probe_config)
    try:
        payload = client.query(bytes([COMM_FW_VERSION]), retries=1)
        firmware = client.get_fw_version_from_payload(payload)
    except Exception as exc:  # noqa: BLE001 - network discovery must be best-effort
        LOG.debug("VESC TCP probe failed for %s:%s: %s", host, port, exc)
        return None
    return VescTcpEndpoint(host=host, port=port, firmware=firmware)


ProbeFunc = Callable[[str, int], VescTcpEndpoint | None]


def discover_vesc_tcp_endpoints(
    discovery_config: VescDiscoveryConfig,
    base_config: VescConfig,
    probe: ProbeFunc | None = None,
) -> list[VescTcpEndpoint]:
    """Discover VESC TCP bridges using only COMM_FW_VERSION reads.

    Discovery is intentionally opt-in and bounded by configured hosts/networks,
    max host count, short timeouts, and a small worker pool.
    """

    if not discovery_config.enabled:
        return []
    hosts = iter_discovery_hosts(discovery_config, configured_host=base_config.host)
    if not hosts:
        return []
    ports = tuple(port for port in discovery_config.ports if 0 < port <= 65535) or (base_config.port,)
    ports = ports[:HARD_MAX_PORTS_PER_SCAN]
    probe_func = probe or (lambda host, port: probe_vesc_tcp(host, port, base_config, discovery_config.probe_timeout_seconds))
    max_probes = max(0, min(discovery_config.max_probes_per_scan, HARD_MAX_PROBES_PER_SCAN))
    tasks = [(host, port) for host in hosts for port in ports][:max_probes]
    if not tasks:
        return []
    endpoints: list[VescTcpEndpoint] = []
    seen: set[str] = set()
    max_workers = max(1, min(discovery_config.max_workers, HARD_MAX_WORKERS, len(tasks)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(probe_func, host, port): (host, port) for host, port in tasks}
        for future in as_completed(future_map):
            host, port = future_map[future]
            try:
                endpoint = future.result()
            except Exception as exc:  # noqa: BLE001 - keep one bad probe from killing scan
                LOG.debug("VESC TCP probe crashed for %s:%s: %s", host, port, exc)
                continue
            if not endpoint:
                continue
            key = endpoint.identity_key
            if key in seen:
                continue
            endpoints.append(endpoint)
            seen.add(key)
    endpoints.sort(key=lambda endpoint: endpoint.key)
    return endpoints
