from __future__ import annotations

import unittest
from unittest.mock import patch

from onewheel_ha_bridge.config import VescConfig, VescDiscoveryConfig
from onewheel_ha_bridge.models import FirmwareInfo
from onewheel_ha_bridge.scanner import HARD_MAX_PORTS_PER_SCAN, HARD_MAX_PROBES_PER_SCAN, HARD_MAX_WORKERS, VescTcpEndpoint, board_id_for_endpoint, discover_vesc_tcp_endpoints, iter_discovery_hosts, probe_vesc_tcp


def firmware(uuid: str = "1234567890abcdef12345678") -> FirmwareInfo:
    return FirmwareInfo(
        major=6,
        minor=5,
        hardware_name="VESC Express",
        uuid=uuid,
        pairing_done=True,
    )


class ScannerTests(unittest.TestCase):
    def test_discovery_is_opt_in(self) -> None:
        calls: list[tuple[str, int]] = []

        endpoints = discover_vesc_tcp_endpoints(
            VescDiscoveryConfig(enabled=False, hosts=("192.0.2.10",)),
            VescConfig(host="192.0.2.1"),
            probe=lambda host, port: calls.append((host, port)) or None,
        )

        self.assertEqual(endpoints, [])
        self.assertEqual(calls, [])

    def test_iter_hosts_dedupes_and_caps_network_scans(self) -> None:
        config = VescDiscoveryConfig(
            enabled=True,
            hosts=("192.0.2.10", "192.0.2.10"),
            networks=("192.0.2.0/30",),
            max_hosts_per_scan=3,
        )
        self.assertEqual(iter_discovery_hosts(config, configured_host="192.0.2.1"), ["192.0.2.1", "192.0.2.10", "192.0.2.2"])

    def test_probe_uses_one_fw_version_query_without_decode_retries(self) -> None:
        expected = firmware()
        with (
            patch("onewheel_ha_bridge.protocol.VescTcpClient.query", return_value=bytes.fromhex("0006055645534320457870726573732054001234567890abcdef12345678010000000000")) as query,
            patch("onewheel_ha_bridge.protocol.VescTcpClient.get_fw_version_from_payload", return_value=expected) as decode,
        ):
            endpoint = probe_vesc_tcp("192.0.2.2", 65102, VescConfig(host="192.0.2.1"), 0.35)

        self.assertIsNotNone(endpoint)
        self.assertEqual(endpoint.firmware, expected)
        self.assertEqual(query.call_args.args, (bytes([0]),))
        self.assertEqual(query.call_args.kwargs, {"retries": 1})
        decode.assert_called_once()

    def test_discover_uses_read_probe_and_sorts_results(self) -> None:
        seen: list[tuple[str, int]] = []

        def probe(host: str, port: int) -> VescTcpEndpoint | None:
            seen.append((host, port))
            if host.endswith("2"):
                return VescTcpEndpoint(host, port, firmware())
            return None

        endpoints = discover_vesc_tcp_endpoints(
            VescDiscoveryConfig(enabled=True, hosts=("192.0.2.2", "192.0.2.3"), ports=(65102,)),
            VescConfig(host="192.0.2.1"),
            probe=probe,
        )

        self.assertEqual([(endpoint.host, endpoint.port) for endpoint in endpoints], [("192.0.2.2", 65102)])
        self.assertIn(("192.0.2.1", 65102), seen)
        self.assertIn(("192.0.2.2", 65102), seen)

    def test_dedupes_by_firmware_uuid(self) -> None:
        endpoints = discover_vesc_tcp_endpoints(
            VescDiscoveryConfig(enabled=True, hosts=("192.0.2.2", "vesc-board.local"), ports=(65102,)),
            VescConfig(host="192.0.2.1"),
            probe=lambda host, port: VescTcpEndpoint(host, port, firmware("abcdef0123456789abcdef01")),
        )
        self.assertEqual(len(endpoints), 1)

    def test_max_probes_caps_host_port_explosion(self) -> None:
        seen: list[tuple[str, int]] = []

        def probe(host: str, port: int) -> None:
            seen.append((host, port))
            return None

        discover_vesc_tcp_endpoints(
            VescDiscoveryConfig(enabled=True, hosts=("192.0.2.2", "192.0.2.3"), ports=(65102, 65103), max_probes_per_scan=2),
            VescConfig(host="192.0.2.1"),
            probe=probe,
        )
        self.assertEqual(len(seen), 2)

    def test_rejects_overbroad_ipv4_network_by_default(self) -> None:
        with self.assertRaises(ValueError):
            iter_discovery_hosts(VescDiscoveryConfig(enabled=True, networks=("192.0.0.0/16",)))

    def test_rejects_public_network_by_default(self) -> None:
        with self.assertRaises(ValueError):
            iter_discovery_hosts(VescDiscoveryConfig(enabled=True, networks=("8.8.8.0/24",)))
        hosts = iter_discovery_hosts(VescDiscoveryConfig(enabled=True, networks=("8.8.8.0/30",), allow_public_networks=True), configured_host=None)
        self.assertEqual(hosts, ["8.8.8.1", "8.8.8.2"])

    def test_hard_caps_total_probes_ports_and_workers(self) -> None:
        seen: list[tuple[str, int]] = []
        hosts = tuple(f"192.0.2.{index}" for index in range(1, 40))
        ports = tuple(range(65000, 65000 + HARD_MAX_PORTS_PER_SCAN + 10))

        class RecordingExecutor:
            max_workers_seen: int | None = None

            def __init__(self, max_workers: int):
                RecordingExecutor.max_workers_seen = max_workers

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def submit(self, func, host, port):
                class Future:
                    def result(self_inner):
                        return func(host, port)

                return Future()

        def probe(host: str, port: int) -> None:
            seen.append((host, port))
            return None

        with patch("onewheel_ha_bridge.scanner.as_completed", side_effect=lambda futures: list(futures)):
            with patch("onewheel_ha_bridge.scanner.ThreadPoolExecutor", RecordingExecutor):
                discover_vesc_tcp_endpoints(
                    VescDiscoveryConfig(
                        enabled=True,
                        hosts=hosts,
                        ports=ports,
                        max_workers=999,
                        max_probes_per_scan=999999,
                    ),
                    VescConfig(host="192.0.2.250"),
                    probe=probe,
                )

        self.assertLessEqual(len(seen), HARD_MAX_PROBES_PER_SCAN)
        self.assertTrue(all(port < 65000 + HARD_MAX_PORTS_PER_SCAN for _, port in seen))
        self.assertEqual(RecordingExecutor.max_workers_seen, HARD_MAX_WORKERS)

    def test_board_id_prefers_firmware_uuid(self) -> None:
        endpoint = VescTcpEndpoint("192.0.2.20", 65102, firmware("abcdef0123456789abcdef01"))
        self.assertEqual(board_id_for_endpoint(endpoint), "vesc_abcdef0123456789abcdef01")

    def test_board_id_uses_full_uuid_to_avoid_truncation_collisions(self) -> None:
        first = VescTcpEndpoint("192.0.2.20", 65102, firmware("abcdef012345000000000001"))
        second = VescTcpEndpoint("192.0.2.21", 65102, firmware("abcdef012345000000000002"))
        self.assertNotEqual(board_id_for_endpoint(first), board_id_for_endpoint(second))

    def test_board_id_falls_back_to_host_port_with_hash_suffix(self) -> None:
        first = VescTcpEndpoint("a.b", 65102, firmware("0" * 24))
        second = VescTcpEndpoint("a-b", 65102, firmware("0" * 24))
        self.assertNotEqual(board_id_for_endpoint(first), board_id_for_endpoint(second))
        self.assertRegex(board_id_for_endpoint(first), r"^vesc_a_b_65102_[0-9a-f]{8}$")


if __name__ == "__main__":
    unittest.main()
