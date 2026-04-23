from __future__ import annotations

import json
import logging
import threading

import paho.mqtt.client as mqtt

from .config import BridgeConfig
from .discovery import availability_topic, build_discovery_payloads, raw_topic, state_topic
from .models import TelemetrySnapshot

LOG = logging.getLogger(__name__)


class HomeAssistantPublisher:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self._connected = threading.Event()
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=config.mqtt.client_id)
        self._client.enable_logger(LOG)
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.will_set(availability_topic(config.home_assistant), payload="offline", retain=True)
        if config.mqtt.username:
            self._client.username_pw_set(config.mqtt.username, config.mqtt.password)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, reason_code, properties):  # noqa: ANN001
        if reason_code == 0:
            LOG.info("connected to MQTT broker %s:%s", self.config.mqtt.host, self.config.mqtt.port)
            self._connected.set()
        else:
            LOG.error("MQTT connect failed with reason %s", reason_code)
            self._connected.clear()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):  # noqa: ANN001
        LOG.warning("disconnected from MQTT broker (reason=%s)", reason_code)
        self._connected.clear()

    def connect(self) -> None:
        self._client.connect(self.config.mqtt.host, self.config.mqtt.port, keepalive=self.config.mqtt.keepalive_seconds)
        self._client.loop_start()
        if not self._connected.wait(timeout=10):
            raise TimeoutError("timed out connecting to MQTT broker")

    def disconnect(self) -> None:
        try:
            self.publish_availability(False)
        finally:
            self._client.loop_stop()
            self._client.disconnect()

    def publish_discovery(self, snapshot: TelemetrySnapshot | None = None) -> None:
        for topic, payload in build_discovery_payloads(self.config.home_assistant, snapshot):
            self._client.publish(topic, json.dumps(payload, separators=(",", ":")), retain=True, qos=1)

    def publish_availability(self, online: bool) -> None:
        payload = "online" if online else "offline"
        self._client.publish(availability_topic(self.config.home_assistant), payload, retain=True, qos=1)

    def publish_snapshot(self, snapshot: TelemetrySnapshot) -> None:
        self._client.publish(
            state_topic(self.config.home_assistant),
            json.dumps(snapshot.to_state_dict(), separators=(",", ":")),
            retain=True,
            qos=1,
        )
        self._client.publish(
            raw_topic(self.config.home_assistant),
            json.dumps(snapshot.to_raw_dict(), separators=(",", ":")),
            retain=True,
            qos=1,
        )
