from __future__ import annotations

import argparse
import json
import logging
import sys

from .bridge import OnewheelBridge
from .config import load_config
from .multibridge import MultiBoardBridge
from .scanner import discover_vesc_tcp_endpoints


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only VESC TCP to Home Assistant bridge for a custom Onewheel")
    parser.add_argument("--config", help="Path to TOML config file", default=None)
    parser.add_argument("--once", action="store_true", help="Poll once, print JSON, and exit")
    parser.add_argument("--discover-once", action="store_true", help="Run one read-only VESC TCP discovery scan, print JSON, and exit")
    parser.add_argument("--raw", action="store_true", help="With --once, print the nested raw snapshot instead of flattened state")
    parser.add_argument("--log-level", default="INFO", help="Logging level (default: INFO)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = load_config(args.config)
    if args.discover_once:
        if not config.discovery.enabled:
            print("discovery is disabled; set [discovery].enabled = true or OWHB_DISCOVERY_ENABLED=true before scanning", file=sys.stderr)
            return 2
        endpoints = discover_vesc_tcp_endpoints(config.discovery, config.vesc)
        payload = [
            {
                "host": endpoint.host,
                "port": endpoint.port,
                "firmware": endpoint.firmware.version,
                "hardware": endpoint.firmware.hardware_name,
                "uuid": endpoint.firmware.uuid,
            }
            for endpoint in endpoints
        ]
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    bridge: OnewheelBridge | MultiBoardBridge
    if args.once:
        # Keep --once as the historical single-board, no-MQTT smoke test even
        # when background discovery is enabled for normal service runs.
        bridge = OnewheelBridge(config)
        bridge.refresh_static_info(force=True)
        snapshot = bridge.poll_once()
        snapshot.firmware = bridge._cached_firmware
        snapshot.can_nodes = list(bridge._cached_can_nodes)
        snapshot.refloat_info = bridge._cached_refloat_info
        snapshot.refloat_ids = bridge._cached_refloat_ids
        bridge.print_snapshot(snapshot, raw=args.raw)
        return 0

    bridge = MultiBoardBridge(config) if config.discovery.enabled else OnewheelBridge(config)
    try:
        bridge.run()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI exit wrapper
        logging.getLogger(__name__).exception("bridge failed: %s", exc)
        return 1
    finally:
        try:
            bridge.close()
        except Exception:  # noqa: BLE001 - shutdown best effort
            logging.getLogger(__name__).debug("bridge close failed", exc_info=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
