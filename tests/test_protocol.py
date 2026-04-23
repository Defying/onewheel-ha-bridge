from __future__ import annotations

import unittest

from onewheel_ha_bridge.config import VescConfig
from onewheel_ha_bridge.protocol import VescTcpClient


FW_HEX = "000605564553432045787072657373205400dc1ed51995e40000000000000000020100000100003bb5e63e"
PING_HEX = "3e0304"
CONTROLLER_HEX = "04010f00df0000000000000000000000000000000000000000000004e500000000000000000000000000000000000000030000000300005265bf03010f010f010f00000009fffffffe00"
BMS_HEX = "6007657ec000000000ffffd017ffffd017000024ae001015861e1032102d102d102d102c102b1029102b102b102d1029102c102b102a102b10291029102a0ffb102b1021102c102d102d1024102310241024102410240000000000000000000000000000000000000000000000000000000000000209b208bf00000f900b0b0960039903e80441162db04483b3be00000000000000000000"
REFLOAT_INFO_HEX = "24650002005265666c6f61740000000000000000000000000001020062657461330000000000000000000000000000008b880d64000027100000000100"
REFLOAT_IDS_HEX = "246520100b6d6f746f722e73706565640a6d6f746f722e6572706d0d6d6f746f722e63757272656e74116d6f746f722e6469725f63757272656e74126d6f746f722e66696c745f63757272656e74106d6f746f722e647574795f6379636c65126d6f746f722e626174745f766f6c74616765126d6f746f722e626174745f63757272656e74116d6f746f722e6d6f736665745f74656d70106d6f746f722e6d6f746f725f74656d7009696d752e706974636811696d752e62616c616e63655f706974636808696d752e726f6c6c0c666f6f747061642e616463310c666f6f747061642e616463320c72656d6f74652e696e7075740a08736574706f696e740c6174722e736574706f696e74136272616b655f74696c742e736574706f696e7414746f727175655f74696c742e736574706f696e74127475726e5f74696c742e736574706f696e740f72656d6f74652e736574706f696e740f62616c616e63655f63757272656e740e6174722e616363656c5f646966660f6174722e73706565645f626f6f73740f626f6f737465722e63757272656e74"
REFLOAT_RT_HEX = "24651f0406027f084602000000800080000000000000000d3657d600004ecb4d9755485544c030129a169a0000000000000000000000"


class ProtocolDecodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = VescTcpClient(VescConfig())

    def test_ping_can_shape(self) -> None:
        nodes = list(bytes.fromhex(PING_HEX)[1:])
        self.assertEqual(nodes, [3, 4])

    def test_fw_parser(self) -> None:
        fw = self.client.get_fw_version_from_payload(bytes.fromhex(FW_HEX))
        self.assertEqual(fw.major, 6)
        self.assertEqual(fw.minor, 5)
        self.assertEqual(fw.hardware_name, "VESC Express T")
        self.assertEqual(fw.version, "6.5")

    def test_controller_parser(self) -> None:
        values = self.client.get_controller_values_from_payload(bytes.fromhex(CONTROLLER_HEX))
        self.assertAlmostEqual(values.temp_fet_c, 27.1, places=1)
        self.assertAlmostEqual(values.temp_motor_c, 22.3, places=1)
        self.assertAlmostEqual(values.vin_v, 125.3, places=1)
        self.assertEqual(values.controller_id, 3)

    def test_bms_parser(self) -> None:
        values = self.client.get_bms_values_from_payload(bytes.fromhex(BMS_HEX))
        self.assertAlmostEqual(values.pack_voltage_v, 124.092096, places=6)
        self.assertEqual(values.min_cell_index, 19)
        self.assertEqual(values.max_cell_index, 1)
        self.assertAlmostEqual(values.cell_delta_v or 0.0, 0.055, places=3)
        self.assertAlmostEqual(values.cell_voltage(19) or 0.0, 4.091, places=3)

    def test_refloat_info_and_rt_parser(self) -> None:
        ids = self.client.get_refloat_ids_from_payload(bytes.fromhex(REFLOAT_IDS_HEX))
        info = self.client.get_refloat_info_from_payload(bytes.fromhex(REFLOAT_INFO_HEX))
        rt = self.client.get_refloat_realtime_from_payload(bytes.fromhex(REFLOAT_RT_HEX), ids)
        self.assertEqual(info.package_name, "Refloat")
        self.assertEqual(info.package_version, "1.2.0-beta3")
        self.assertEqual(rt.package_state, "READY")
        self.assertEqual(rt.package_mode, "NORMAL")
        self.assertFalse(rt.wheelslip)
        self.assertIn("motor.speed", rt.values)


if __name__ == "__main__":
    unittest.main()
