from __future__ import annotations

import unittest

from onewheel_ha_bridge.models import BmsValues, RefloatLights, RefloatRealtime, TelemetrySnapshot


def make_bms(current_a: float, balancing_state: list[bool] | None = None) -> BmsValues:
    return BmsValues(
        pack_voltage_v=122.0,
        charge_voltage_v=122.0,
        current_a=current_a,
        current_ic_a=current_a,
        amp_hours=0.0,
        watt_hours=0.0,
        cells_v=[4.05, 4.06, 4.07],
        balancing_state=balancing_state if balancing_state is not None else [False, False, False],
        temps_c=[],
        temp_ic_c=0.0,
        temp_humidity_c=0.0,
        humidity_pct=0.0,
        temp_max_cell_c=0.0,
        soc_ratio=0.5,
        soh_ratio=1.0,
        can_id=4,
        amp_hours_charged_total=0.0,
        watt_hours_charged_total=0.0,
        amp_hours_discharged_total=0.0,
        watt_hours_discharged_total=0.0,
    )


def make_refloat(charging: bool) -> RefloatRealtime:
    return RefloatRealtime(
        mask=0,
        extra_flags=0,
        time_ticks=0,
        package_state="READY",
        package_mode="NORMAL",
        footpad_state="NONE",
        charging=charging,
        darkride=False,
        wheelslip=False,
        stop_condition="NONE",
        sat="NONE",
        alert_reason="NONE",
        values={},
        runtime_values={},
        charging_values={},
        active_alert_mask_low=0,
        active_alert_mask_high=0,
        firmware_fault_code=0,
    )


class ModelStateTests(unittest.TestCase):
    def test_charging_is_derived_from_positive_ennoid_pack_current(self) -> None:
        state = TelemetrySnapshot(bms=make_bms(1.04), refloat_realtime=make_refloat(False)).to_state_dict()
        self.assertTrue(state["charging"])
        self.assertFalse(state["refloat_charging"])

    def test_near_zero_or_negative_current_is_not_charging(self) -> None:
        self.assertFalse(TelemetrySnapshot(bms=make_bms(0.05)).to_state_dict()["charging"])
        self.assertFalse(TelemetrySnapshot(bms=make_bms(-1.0)).to_state_dict()["charging"])

    def test_balancing_state_is_derived_from_bms_bleed_bytes(self) -> None:
        state = TelemetrySnapshot(bms=make_bms(0.0, [False, True, True])).to_state_dict()
        self.assertTrue(state["balancing_active"])
        self.assertEqual(state["balancing_cell_count"], 2)

    def test_expanded_refloat_and_bms_state_fields(self) -> None:
        refloat = make_refloat(False)
        refloat.values.update({"motor.erpm": 1234.0, "imu.pitch": 1.25})
        refloat.runtime_values.update({"balance_current": 2.5})
        refloat.charging_values.update({"charging_voltage": 124.0})
        state = TelemetrySnapshot(
            bms=make_bms(0.0),
            refloat_realtime=refloat,
            refloat_lights=RefloatLights(leds_on=True, headlights_on=False, raw_flags=1),
        ).to_state_dict()

        self.assertEqual(state["soh_percent"], 100.0)
        self.assertEqual(state["cell_2_v"], 4.06)
        self.assertEqual(state["motor_erpm"], 1234.0)
        self.assertEqual(state["imu_pitch_deg"], 1.25)
        self.assertEqual(state["balance_current_a"], 2.5)
        self.assertEqual(state["refloat_charging_voltage_v"], 124.0)
        self.assertTrue(state["refloat_leds_on"])


if __name__ == "__main__":
    unittest.main()
