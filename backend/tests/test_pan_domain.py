"""锅温日志升级与揉捻接料证明测试。

覆盖：旧口径回查、设备日志独立满足新要求、每锅唯一有效证明、缺测量时间不合格、
切换期两种格式同办、重复补传/重复接料不扣料、回滚保留历史、未办成旧记录可查。
"""
from __future__ import annotations

import unittest

from app.services import service_for
from app.services.pan import (
    DEVICE_SOURCE,
    LEGACY_SOURCE,
    LEGACY_VERSION,
    NEW_VERSION,
    pan_service,
)
from app.store import store


def _reset_pan_state() -> None:
    store.pan_legacy_logs.clear()
    store.pan_logs.clear()
    store.pan_proofs.clear()
    store.pan_receipts.clear()
    store.pan_state.update({
        "mode": "new",
        "rollback_at": None,
        "seq": {"log": 0, "proof": 0, "receipt": 0},
    })


def _make_fixing(status: str = "待确认", setting: str = "200",
                 pot: str | None = None) -> dict:
    fixing_svc = service_for("fixing")
    values = {"锅温设定": setting, "杀青时长": "5", "投叶量": "10"}
    if pot:
        values["锅号"] = pot
    entry, errors = fixing_svc.create_entry(values)
    assert entry is not None, errors
    entry["status"] = status
    if status == "已确认":
        entry["产出重量"] = 80
    return entry


def _make_rolling(pot: str) -> dict:
    rolling_svc = service_for("rolling")
    entry, errors = rolling_svc.create_entry({
        "压力档位": "中压", "揉捻时长": "8", "成条率": "90",
        "碎茶比例": "2", "锅号": pot,
    })
    assert entry is not None, errors
    return entry


class TestLegacyMigrationAndQuery(unittest.TestCase):
    """迁移只做告知来源，旧设定不能当实测温度。"""

    def setUp(self):
        _reset_pan_state()

    def test_migration_keeps_legacy_source_and_query(self):
        fixing = _make_fixing(status="已确认", setting="200", pot="POT-LEGACY")
        result = pan_service.migrate_legacy([fixing["id"]])
        self.assertEqual(result["created"], 1)

        # 重复迁移不重复生成
        again = pan_service.migrate_legacy([fixing["id"]])
        self.assertEqual(again["created"], 0)
        self.assertEqual(again["skipped"], 1)

        legacy = pan_service.legacy_query()
        row = next(x for x in legacy["items"] if x["锅号"] == "POT-LEGACY")
        self.assertEqual(row["锅温设定"], "200")
        self.assertEqual(row["口径"], "旧口径")
        self.assertFalse(row["实测"])

        proof = pan_service.get_proof("POT-LEGACY")
        self.assertEqual(proof["告知来源"][0]["来源"], LEGACY_SOURCE)
        self.assertFalse(proof["告知来源"][0]["实测"])

    def test_unconfirmed_legacy_setting_not_received(self):
        _make_fixing(status="待确认", setting="200", pot="POT-DRAFT")
        pan_service.migrate_legacy()
        proof, message, reconcile = pan_service.ensure_proof("POT-DRAFT")
        self.assertIsNone(proof)
        self.assertFalse(reconcile["原旧凭据继续受理"])


class TestDeviceLogNewRequirement(unittest.TestCase):
    """设备锅温日志要独立满足新要求：有时间 + 已确认 + 温度合格。"""

    def setUp(self):
        _reset_pan_state()

    def test_log_without_measure_time_cannot_be_qualified(self):
        fixing = _make_fixing(status="待确认", pot="POT-NOTIME")
        log, _ = pan_service.upload_device_log({
            "锅号": "POT-NOTIME", "杀青记录ID": fixing["id"],
            "实测锅温": "220", "测温时间": "",
        })
        self.assertFalse(log["有测量时间"])
        confirmed, message = pan_service.confirm_log(log["id"])
        self.assertIsNone(confirmed)
        self.assertIn("缺少实际测量时间", message)

        proof, message, reconcile = pan_service.ensure_proof("POT-NOTIME")
        self.assertIsNone(proof)
        self.assertTrue(reconcile["原旧凭据继续受理"] is False)
        self.assertIn("不能当作实测合格", message)

    def test_device_log_qualifies_while_legacy_pending(self):
        """旧系统待确认杀青 + 设备独立合格的锅温日志 -> 新证生效。"""
        fixing = _make_fixing(status="待确认", pot="POT-PENDING")
        pan_service.migrate_legacy([fixing["id"]])

        log, message = pan_service.upload_device_log({
            "锅号": "POT-PENDING", "杀青记录ID": fixing["id"],
            "实测锅温": "220", "测温时间": "2026-11-27 10:30",
        })
        self.assertIn("待确认", message)

        before = pan_service.get_proof("POT-PENDING")
        self.assertTrue(before["核对"]["需要确认刚来的锅温日志"])
        self.assertFalse(before["核对"]["原旧凭据继续受理"])

        log, _ = pan_service.confirm_log(log["id"])
        self.assertEqual(log["状态"], "已确认")
        self.assertTrue(log["有测量时间"])

        proof = pan_service.get_proof("POT-PENDING")
        self.assertIsNotNone(proof["有效证明"])
        self.assertEqual(proof["有效证明"]["凭据版本"], NEW_VERSION)
        self.assertTrue(proof["有效证明"]["实测"])
        self.assertEqual(proof["核对"]["实际采用"], NEW_VERSION)
        # 两种告知来源都保留
        self.assertEqual(proof["核对"]["告知来源数"], 2)
        sources = {s["来源"] for s in proof["告知来源"]}
        self.assertEqual(sources, {LEGACY_SOURCE, DEVICE_SOURCE})


class TestSingleProofPerPot(unittest.TestCase):
    """同一锅两个来源、切换期两种格式同办，也只出一份有效证明。"""

    def setUp(self):
        _reset_pan_state()

    def test_confirmed_legacy_first_keeps_legacy_proof(self):
        fixing = _make_fixing(status="已确认", pot="POT-OLD-FIRST")
        pan_service.migrate_legacy([fixing["id"]])
        # 设备日志后到但待确认
        pan_service.upload_device_log({
            "锅号": "POT-OLD-FIRST", "杀青记录ID": fixing["id"],
            "实测锅温": "240", "测温时间": "2026-11-27 11:00",
        })
        proof1, message1, reconcile1 = pan_service.ensure_proof("POT-OLD-FIRST")
        self.assertEqual(proof1["凭据版本"], LEGACY_VERSION)
        self.assertTrue(reconcile1["原旧凭据继续受理"])
        self.assertTrue(reconcile1["需要确认刚来的锅温日志"])
        self.assertIn("未采用", message1)

        # 即便后来的日志被确认，这一锅仍沿用老证明，不另出一份
        log = store.pan_logs[-1]
        pan_service.confirm_log(log["id"])
        proof2, message2, _ = pan_service.ensure_proof("POT-OLD-FIRST")
        self.assertEqual(proof2["id"], proof1["id"])
        self.assertEqual(proof2["凭据版本"], LEGACY_VERSION)
        self.assertIn("继续沿用", message2)
        self.assertEqual(
            len([p for p in store.pan_proofs if p["锅号"] == "POT-OLD-FIRST"]), 1)

    def test_two_receipts_same_pot_blocked(self):
        fixing = _make_fixing(status="已确认", pot="POT-TWO")
        pan_service.migrate_legacy([fixing["id"]])
        r1 = _make_rolling("POT-TWO")
        r2 = _make_rolling("POT-TWO")

        receipt1, message1, _ = pan_service.receive(r1["id"], "POT-TWO")
        self.assertIsNotNone(receipt1)
        self.assertEqual(receipt1["凭据版本"], LEGACY_VERSION)
        self.assertEqual(receipt1["接料重量"], 80.0)

        receipt2, message2, _ = pan_service.receive(r2["id"], "POT-TWO")
        self.assertEqual(receipt2["id"], receipt1["id"])
        self.assertIn("不重复扣料", message2)
        self.assertEqual(len(store.pan_receipts), 1)


class TestIdempotentDelivery(unittest.TestCase):
    """补传相同日志、重新进入工作台、重复接料都不重新扣料。"""

    def setUp(self):
        _reset_pan_state()

    def test_duplicate_log_and_repeat_receive(self):
        fixing = _make_fixing(status="待确认", pot="POT-IDEM")
        payload = {
            "锅号": "POT-IDEM", "杀青记录ID": fixing["id"],
            "实测锅温": "230", "测温时间": "2026-11-27 09:15",
        }
        log1, _ = pan_service.upload_device_log(payload)
        log2, message = pan_service.upload_device_log(payload)
        self.assertEqual(log1["id"], log2["id"])
        self.assertEqual(len([x for x in store.pan_logs
                              if x["来源"] == DEVICE_SOURCE and x["锅号"] == "POT-IDEM"]), 1)
        self.assertIn("未重复登记", message)

        pan_service.confirm_log(log1["id"]) if log1["状态"] != "已确认" else None
        rolling = _make_rolling("POT-IDEM")

        receipt1, _, _ = pan_service.receive(rolling["id"], "POT-IDEM")
        self.assertEqual(receipt1["凭据版本"], NEW_VERSION)
        # 重新进入工作台只是查询，不扣料
        plan = service_for("rolling").receive_plan(rolling["id"])
        self.assertIsNotNone(plan["已接料"])
        # 再次接料
        receipt2, message, _ = pan_service.receive(rolling["id"], "POT-IDEM")
        self.assertEqual(receipt2["id"], receipt1["id"])
        self.assertIn("不重复扣料", message)
        self.assertEqual(len(store.pan_receipts), 1)
        self.assertEqual(rolling["产出重量"] is not None, True)


class TestSwitchRollback(unittest.TestCase):
    """切换/回滚：已办成接料保留当时版本，回切后历史与新接料口径正确。"""

    def setUp(self):
        _reset_pan_state()

    def test_rollback_keeps_receipt_version_and_new_receipts_use_legacy(self):
        # 切换期：一锅用新版接料
        fixing_new = _make_fixing(status="待确认", pot="POT-NEW")
        log, _ = pan_service.upload_device_log({
            "锅号": "POT-NEW", "杀青记录ID": fixing_new["id"],
            "实测锅温": "225", "测温时间": "2026-11-27 12:00",
        })
        pan_service.confirm_log(log["id"])
        rolling_new = _make_rolling("POT-NEW")
        receipt_new, _, _ = pan_service.receive(rolling_new["id"], "POT-NEW")
        self.assertEqual(receipt_new["凭据版本"], NEW_VERSION)

        # 回滚到旧环境
        state, message = pan_service.set_mode("legacy")
        self.assertEqual(state["mode"], "legacy")
        self.assertIn("回滚", message)

        # 已办成接料历史保留原版本
        history = pan_service.receipts_for_rolling(rolling_new["id"])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["凭据版本"], NEW_VERSION)
        # 沿用已有证明也不再扣料
        receipt_again, msg, _ = pan_service.receive(rolling_new["id"], "POT-NEW")
        self.assertEqual(receipt_again["id"], receipt_new["id"])
        self.assertIn("不重复扣料", msg)

        # 回滚后新锅只受理旧凭据
        fixing_old = _make_fixing(status="已确认", pot="POT-ROLLBACK-OLD")
        pan_service.migrate_legacy([fixing_old["id"]])
        rolling_old = _make_rolling("POT-ROLLBACK-OLD")
        receipt_old, _, _ = pan_service.receive(rolling_old["id"], "POT-ROLLBACK-OLD")
        self.assertEqual(receipt_old["凭据版本"], LEGACY_VERSION)

        # 回滚后新格式不能单独出证
        fixing_only_new = _make_fixing(status="待确认", pot="POT-ONLY-NEW")
        log2, _ = pan_service.upload_device_log({
            "锅号": "POT-ONLY-NEW", "杀青记录ID": fixing_only_new["id"],
            "实测锅温": "230", "测温时间": "2026-11-27 13:00",
        })
        pan_service.confirm_log(log2["id"])
        proof, message, _ = pan_service.ensure_proof("POT-ONLY-NEW")
        self.assertIsNone(proof)
        self.assertIn("回滚", message)

        # 未办成的旧记录仍可查
        pending = pan_service.pending_receiving()
        self.assertTrue(any(x["锅号"] == "POT-ONLY-NEW" for x in pending))
        self.assertFalse(any(x["锅号"] == "POT-NEW" for x in pending))

        # 切回新版
        pan_service.set_mode("new")
        proof, _, _ = pan_service.ensure_proof("POT-ONLY-NEW")
        self.assertEqual(proof["凭据版本"], NEW_VERSION)


class TestRollingStationLookup(unittest.TestCase):
    """揉捻工位能查接料证明并完成接料。"""

    def setUp(self):
        _reset_pan_state()

    def test_receive_plan_and_receive(self):
        fixing = _make_fixing(status="已确认", pot="POT-STATION")
        pan_service.migrate_legacy([fixing["id"]])
        rolling = _make_rolling("POT-STATION")

        plan = service_for("rolling").receive_plan(rolling["id"])
        self.assertIsNone(plan["已接料"])
        self.assertIn("原旧凭据继续受理", plan["核对"])
        self.assertTrue(plan["核对"]["原旧凭据继续受理"])

        receipt, message = service_for("rolling").receive(rolling["id"])
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt["凭据版本"], LEGACY_VERSION)
        self.assertEqual(rolling["接料已扣料"], True)

        history = service_for("rolling").receive_history(rolling["id"])
        self.assertEqual(len(history), 1)

    def test_crew_confirms_legacy_fixing_then_advances_to_rolling(self):
        """班组从旧记录确认杀青，再推进到揉捻接料；核对写明用了哪一份凭据。"""
        from app.services.pipeline import pipeline

        fixing = _make_fixing(status="待确认", pot="POT-CREW")
        service_for("fixing").run_action(fixing["id"], "记录杀青")
        self.assertEqual(fixing["status"], "已确认")

        for r in store.rows("testing"):
            r["status"] = "已确认"
        for r in store.rows("certification"):
            r["status"] = "已确认"
            r["有效期至"] = "2027-12-31"

        rolling, message = pipeline.advance_batch(
            "fixing", fixing["id"], "BATCH-CREW", request_id="crew-1")
        self.assertIsNotNone(rolling, message)
        self.assertEqual(rolling["上游工序"], "fixing")
        self.assertEqual(rolling["上游记录ID"], fixing["id"])

        pot = service_for("rolling").pot_key(rolling)
        self.assertEqual(pot, "POT-CREW")
        plan = service_for("rolling").receive_plan(rolling["id"])
        self.assertTrue(plan["核对"]["原旧凭据继续受理"])
        self.assertFalse(plan["核对"]["需要确认刚来的锅温日志"])

        receipt, message = service_for("rolling").receive(rolling["id"])
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt["凭据版本"], LEGACY_VERSION)
        self.assertEqual(rolling["接料核对结论"],
                         "原旧锅温设定凭据继续受理并已实际采用")
        self.assertIn("使用接料凭据", message)

        # 重新进入工作台（再查一次）不重新扣料
        again, message = service_for("rolling").receive(rolling["id"])
        self.assertEqual(again["id"], receipt["id"])
        self.assertIn("不重复扣料", message)
        self.assertEqual(len(store.pan_receipts), 1)


if __name__ == "__main__":
    unittest.main()
