"""杀青锅温日志与揉捻接料证明（升级迁移域）。

升级前杀青只有单个「锅温设定」；升级后设备按实际测量时间上报「锅温日志」。
这里把两件事拆开：

* 旧口径：已确认的「锅温设定」与「出料重量」只按旧口径回查，绝不当成设备后来
  实测到的温度。旧记录迁移成一条「旧锅温设定」告知来源，保留原文与出料重量。
* 新口径：设备锅温日志必须带真实「测温时间」且经确认，才算实测合格，才能成为
  新版接料凭据。

每口锅（锅号）最多只有一份「有效」接料证明；旧版（旧锅温设定）与新版（设备锅温
日志）两种来源同时存在时，谁先形成有效证明就沿用谁，另一方面保留为告知来源并在
核对结论里说明「原旧凭据是否继续受理」「刚来的锅温日志是否需要确认」「实际采用
了哪一份」。

切换/回滚：已确认揉捻保留当时实际使用的凭据版本；补传相同日志、重新进入工作台
或重复接料都不会再次扣料；回切后已办成的接料仍有历史，没办成的旧记录仍然可查。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

LEGACY_SOURCE = "旧锅温设定"
DEVICE_SOURCE = "设备锅温日志"

LEGACY_VERSION = "旧版锅温设定"
NEW_VERSION = "新版锅温日志"

MIN_TEMP = 180.0
MAX_TEMP = 350.0


def _parse_measure_time(value: Any) -> datetime | None:
    """解析实际测量时间；解析不了就等于没有测量时间。"""
    text = str(value or "").strip().replace("T", " ")
    if not text:
        return None
    # 只有日期没有时刻不算「实际测量时间」：无法确认是哪一锅哪一刻的实测。
    candidates = [
        (text[:19], "%Y-%m-%d %H:%M:%S"),
        (text[:16], "%Y-%m-%d %H:%M"),
    ]
    for part, fmt in candidates:
        try:
            return datetime.strptime(part, fmt)
        except ValueError:
            continue
    return None


def _parse_temp(value: Any) -> float:
    try:
        return float(str(value).replace("℃", "").strip())
    except (TypeError, ValueError):
        return 0.0


class PanService:

    # ── 锅号与来源 ──

    def pot_key_for_fixing(self, entry: dict[str, Any]) -> str:
        explicit = str(entry.get("锅号") or "").strip()
        if explicit:
            return explicit
        return f"FIXING#{entry['id']}"

    def _fixing_of_log(self, log: dict[str, Any]) -> dict[str, Any] | None:
        fid = log.get("杀青记录ID")
        if fid in (None, ""):
            return None
        try:
            return store.find("fixing", int(fid))
        except (TypeError, ValueError):
            return None

    def _legacy_usable(self, log: dict[str, Any]) -> bool:
        """旧锅温设定只有在杀青记录已确认后，才继续作为原旧凭据受理。"""
        fixing = self._fixing_of_log(log)
        if fixing is not None:
            return fixing.get("status") == "已确认"
        return bool(log.get("可受理"))

    def _device_status(self, log: dict[str, Any]) -> tuple[bool, str]:
        """判断设备锅温日志能否独立满足新要求（已确认 + 有真实测量时间 + 温度合格）。"""
        if log.get("状态") != "已确认":
            return False, "锅温日志尚未确认"
        if not log.get("有测量时间"):
            return False, "锅温日志缺少实际测量时间，不能当作实测合格"
        temp = _parse_temp(log.get("实测锅温"))
        if temp < MIN_TEMP or temp > MAX_TEMP:
            return False, f"实测锅温 {log.get('实测锅温')}℃ 超出 {MIN_TEMP:.0f}-{MAX_TEMP:.0f}℃"
        return True, "实测锅温合格"

    def _logs_for_pot(self, pot: str) -> list[dict[str, Any]]:
        return [
            log for log in store.pan_logs
            if log.get("锅号") == pot
        ]

    def _effective_proof(self, pot: str) -> dict[str, Any] | None:
        # 「已使用」仍是该锅的唯一有效证明：用完也不允许再出第二份。
        for proof in store.pan_proofs:
            if proof.get("锅号") == pot and proof.get("状态") in ("有效", "已使用"):
                return proof
        return None

    # ── 旧记录迁移 ──

    def migrate_legacy(self, fixing_ids: list[int] | None = None) -> dict[str, Any]:
        """把旧环境已存的「锅温设定」迁移成旧版告知来源；可重复执行，不重复迁移。"""
        created: list[dict[str, Any]] = []
        skipped: list[int] = []
        targets = store.rows("fixing")
        if fixing_ids is not None:
            wanted = {int(i) for i in fixing_ids}
            targets = [row for row in targets if int(row.get("id", 0)) in wanted]

        for row in targets:
            fixing_id = int(row.get("id", 0))
            setting = row.get("锅温设定")
            if not str(setting or "").strip():
                continue
            existing = [
                log for log in store.pan_legacy_logs
                if log.get("杀青记录ID") == fixing_id
            ]
            if existing:
                skipped.append(fixing_id)
                continue
            pot = self.pot_key_for_fixing(row)
            log = {
                "id": store.next_pan_id("log"),
                "日志编号": f"LEGACY-{fixing_id:04d}",
                "锅号": pot,
                "杀青记录ID": fixing_id,
                "批次号": row.get("批次号", ""),
                "来源": LEGACY_SOURCE,
                "告知来源": "旧系统迁移",
                "口径": "旧口径",
                # 原文照搬：旧锅温设定不是设备后来实测到的温度。
                "锅温设定": setting,
                "出料重量": row.get("产出重量", row.get("出料重量", "")),
                "实测锅温": None,
                "测温时间": "",
                "有测量时间": False,
                "可受理": row.get("status") == "已确认",
                "迁移时间": datetime.now().isoformat(timespec="seconds"),
            }
            store.pan_legacy_logs.append(log)
            store.pan_logs.append(log)
            created.append(dict(log))

        return {
            "created": len(created),
            "skipped": len(skipped),
            "logs": created,
            "总数": {
                "legacy_logs": len(store.pan_legacy_logs),
                "device_logs": len(store.pan_logs) - len(store.pan_legacy_logs),
            },
            "告示": "旧锅温设定按旧口径保留，不作为设备实测温度；两种告知来源同时可查",
        }

    def legacy_query(self, confirmed_only: bool = True) -> dict[str, Any]:
        """已确认的锅温设定与出料重量继续按旧口径回查。"""
        rows: list[dict[str, Any]] = []
        for row in store.rows("fixing"):
            if not str(row.get("锅温设定") or "").strip():
                continue
            if confirmed_only and row.get("status") != "已确认":
                continue
            rows.append({
                "id": int(row.get("id", 0)),
                "批次号": row.get("批次号", ""),
                "锅号": self.pot_key_for_fixing(row),
                "锅温设定": row.get("锅温设定", ""),
                "出料重量": row.get("产出重量", row.get("出料重量", "")),
                "status": row.get("status", ""),
                "口径": "旧口径",
                "实测": False,
                "说明": "旧锅温设定不是设备后来实际测得的温度",
            })
        return {
            "口径": "旧口径",
            "confirmed_only": confirmed_only,
            "total": len(rows),
            "items": rows,
        }

    # ── 设备锅温日志 ──

    def _fingerprint(self, pot: str, fixing_id: Any, measure_time: str, temp: Any) -> str:
        # 以锅 + 测量时间 + 实测温度作为去重键：同一锅同一份日志无论带不带杀青记录ID
        # 都认作同一份，补传不会重复登记，也不会重复扣料。
        return f"{pot}|{measure_time}|{_parse_temp(temp)}"

    def find_log(self, log_no: str | None = None,
                 fingerprint: str | None = None) -> dict[str, Any] | None:
        for log in store.pan_logs:
            if log_no and log.get("日志编号") == log_no and log.get("来源") == DEVICE_SOURCE:
                return log
            if fingerprint and log.get("指纹") == fingerprint:
                return log
        return None

    def upload_device_log(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """设备上传锅温日志。同一锅同一份日志补传只返回原记录，不重复登记。"""
        pot = str(values.get("锅号") or "").strip()
        fixing_id = values.get("杀青记录ID")
        if fixing_id in ("", None) and not pot:
            return None, "锅温日志必须提供锅号或杀青记录ID"
        if fixing_id not in ("", None):
            try:
                fixing_id = int(fixing_id)
            except (TypeError, ValueError):
                return None, "杀青记录ID必须是整数"
            fixing = store.find("fixing", fixing_id)
            if fixing is None:
                return None, f"杀青记录 {fixing_id} 不存在"
            derived = self.pot_key_for_fixing(fixing)
            if pot and pot != derived:
                return None, f"锅号 {pot} 与杀青记录 {fixing_id} 的锅号 {derived} 不一致"
            pot = derived
            batch_no = fixing.get("批次号", "")
        else:
            batch_no = values.get("批次号", "")

        temp_raw = values.get("实测锅温")
        temp = _parse_temp(temp_raw)
        if temp <= 0:
            return None, "锅温日志必须提供实测锅温"
        if temp < MIN_TEMP or temp > MAX_TEMP:
            return None, f"实测锅温不得低于{MIN_TEMP:.0f}℃或高于{MAX_TEMP:.0f}℃"

        measure_time_raw = str(values.get("测温时间") or "").strip()
        measure_time = _parse_measure_time(measure_time_raw)
        normalized_time = measure_time.isoformat(sep=" ") if measure_time else ""
        log_no = str(values.get("日志编号") or "").strip()
        fingerprint = self._fingerprint(pot, fixing_id, normalized_time, temp)

        existing = self.find_log(log_no or None, fingerprint)
        if existing is not None:
            return existing, "相同锅温日志已存在，未重复登记，也未重复扣料"

        log = {
            "id": store.next_pan_id("log"),
            "日志编号": log_no or f"PAN-{store.pan_state['seq']['log']:04d}",
            "锅号": pot,
            "杀青记录ID": fixing_id,
            "批次号": batch_no,
            "来源": DEVICE_SOURCE,
            "告知来源": "设备上报",
            "口径": "新口径" if measure_time else "未提供测量时间",
            "实测锅温": temp,
            "测温时间": normalized_time,
            "有测量时间": measure_time is not None,
            "状态": "待确认",
            "指纹": fingerprint,
            "上传时间": datetime.now().isoformat(timespec="seconds"),
        }
        store.pan_logs.append(log)
        if measure_time is None:
            return log, "锅温日志已登记，但缺少实际测量时间，确认前不能当作实测合格"
        return log, "锅温日志已登记，待确认实测温度"

    def confirm_log(self, log_id: int) -> tuple[dict[str, Any] | None, str]:
        """确认设备锅温日志；缺测量时间的日志不能确认成实测合格。"""
        log = next((x for x in store.pan_logs if int(x.get("id", 0)) == int(log_id)), None)
        if log is None:
            return None, f"锅温日志 {log_id} 不存在"
        if log.get("来源") != DEVICE_SOURCE:
            return None, "旧锅温设定不需要走设备日志确认，按旧口径受理"
        if log.get("状态") == "已确认":
            return log, "锅温日志已确认，无需重复确认"
        if not log.get("有测量时间"):
            return None, "锅温日志缺少实际测量时间，不能确认，也不能当作实测合格"
        ok, reason = self._device_status({**log, "状态": "已确认"})
        if not ok:
            return None, reason
        log["状态"] = "已确认"
        log["确认时间"] = datetime.now().isoformat(timespec="seconds")
        store.log_event("pan", int(log["id"]), "confirm_log", {"锅号": log.get("锅号")})
        return log, f"锅温日志 {log.get('日志编号')} 已确认，可作为实测合格凭据"

    # ── 接料证明 ──

    def _sources_summary(self, pot: str) -> list[dict[str, Any]]:
        summary: list[dict[str, Any]] = []
        for log in self._logs_for_pot(pot):
            if log.get("来源") == LEGACY_SOURCE:
                summary.append({
                    "来源": LEGACY_SOURCE,
                    "日志编号": log.get("日志编号"),
                    "锅温设定": log.get("锅温设定"),
                    "出料重量": log.get("出料重量"),
                    "口径": "旧口径",
                    "实测": False,
                    "可受理": self._legacy_usable(log),
                    "告知来源": log.get("告知来源"),
                })
            else:
                ok, reason = self._device_status(log)
                summary.append({
                    "来源": DEVICE_SOURCE,
                    "日志编号": log.get("日志编号"),
                    "实测锅温": log.get("实测锅温"),
                    "测温时间": log.get("测温时间"),
                    "有测量时间": bool(log.get("有测量时间")),
                    "口径": "新口径",
                    "实测": bool(log.get("有测量时间")),
                    "状态": log.get("状态"),
                    "可用": ok,
                    "说明": reason,
                    "告知来源": log.get("告知来源"),
                })
        return summary

    def _reconcile(self, pot: str, proof: dict[str, Any] | None) -> dict[str, Any]:
        """核对旧凭据是否继续受理、新日志是否还要确认、实际采用哪一份。"""
        sources = self._sources_summary(pot)
        legacy = [s for s in sources if s["来源"] == LEGACY_SOURCE]
        device = [s for s in sources if s["来源"] == DEVICE_SOURCE]
        legacy_ok = any(s["可受理"] for s in legacy)
        device_ok = any(s["可用"] for s in device)
        device_pending = [
            s for s in device
            if s.get("状态") == "待确认" and s.get("有测量时间")
        ]
        device_no_time = [s for s in device if not s.get("有测量时间")]
        return {
            "锅号": pot,
            "原旧凭据继续受理": legacy_ok,
            "需要确认刚来的锅温日志": bool(device_pending) and not device_ok,
            "实际采用": (proof or {}).get("凭据版本"),
            "实际采用证明ID": (proof or {}).get("id"),
            "实际采用证明编号": (proof or {}).get("证明编号"),
            "实际采用日志": (proof or {}).get("依据日志编号"),
            "说明": self._reconcile_note(proof, legacy_ok, device_ok, device_pending, device_no_time),
            "告知来源数": len(sources),
        }

    def _reconcile_note(self, proof: dict[str, Any] | None, legacy_ok: bool,
                        device_ok: bool, device_pending: list[dict[str, Any]],
                        device_no_time: list[dict[str, Any]]) -> str:
        if proof is None:
            if device_pending:
                return "刚来的锅温日志尚未确认，需先确认才能作为实测合格凭据"
            if device_no_time:
                return "锅温日志缺少实际测量时间，不能当作实测合格"
            if legacy_ok:
                return "原旧锅温设定凭据继续受理，可查证明后接料"
            if device_ok:
                return "已有确认过的实测锅温日志，可查证明后接料"
            if not legacy_ok and not device_ok:
                return "该锅尚无可用接料凭据"
        if proof is not None and proof.get("凭据版本") == LEGACY_VERSION:
            note = "原旧锅温设定凭据继续受理并已实际采用"
            if device_pending:
                note += "；刚来的锅温日志尚未确认，本次未采用"
            elif device_no_time:
                note += "；刚来的锅温日志缺少测量时间，不能当作实测合格"
            return note
        if proof is not None:
            note = "实际采用新版设备锅温日志（含真实测量时间）"
            if legacy_ok:
                note += "；原旧凭据仍可继续受理，但每锅只保留一份有效证明"
            return note
        return ""

    def ensure_proof(self, pot: str) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
        """为一口锅建立（或沿用）唯一有效接料证明。"""
        existing = self._effective_proof(pot)
        if existing is not None:
            reconcile = self._reconcile(pot, existing)
            return existing, (
                f"该锅已有有效接料证明 {existing['证明编号']}（{existing['凭据版本']}），"
                "继续沿用，不重复出证"
            ), reconcile

        # 没跑过迁移的旧环境：只要杀青记录本身有锅温设定，就按旧口径补登记告知来源。
        if not self._logs_for_pot(pot):
            for row in store.rows("fixing"):
                if self.pot_key_for_fixing(row) == pot and str(row.get("锅温设定") or "").strip():
                    self.migrate_legacy([int(row.get("id", 0))])
                    break

        logs = self._logs_for_pot(pot)
        if not logs:
            reconcile = self._reconcile(pot, None)
            return None, f"锅号 {pot} 没有锅温告知来源，无法出证", reconcile

        legacy_logs = [x for x in logs if x.get("来源") == LEGACY_SOURCE and self._legacy_usable(x)]
        device_logs = [x for x in logs if x.get("来源") == DEVICE_SOURCE]
        usable_new = [
            x for x in device_logs
            if self._device_status(x)[0]
        ]
        pending_new = [
            x for x in device_logs
            if x.get("状态") == "待确认" and x.get("有测量时间")
        ]
        no_time_new = [x for x in device_logs if not x.get("有测量时间")]

        mode = store.pan_state.get("mode", "new")
        # 回滚到旧环境后，只允许用旧版锅温设定新出证；切换期已生效的新证仍沿用。
        allow_new = mode != "legacy"

        if usable_new and allow_new:
            basis = max(usable_new, key=lambda x: _parse_measure_time(x.get("测温时间")) or datetime.min)
            proof = self._create_proof(pot, basis, NEW_VERSION)
            message = (
                f"已按设备锅温日志 {basis.get('日志编号')} 出证：实测 {basis.get('实测锅温')}℃，"
                f"测量时间 {basis.get('测温时间')}"
            )
            if legacy_logs:
                message += "；原旧锅温设定仍作为另一种告知来源保留，每锅只保留这一份有效证明"
            if no_time_new:
                message += "；另有锅温日志缺少测量时间，不能当作实测合格"
            return proof, message, self._reconcile(pot, proof)

        if legacy_logs:
            basis = legacy_logs[0]
            proof = self._create_proof(pot, basis, LEGACY_VERSION)
            message = (
                f"已按原旧锅温设定出证：锅温设定 {basis.get('锅温设定')}，"
                "按旧口径受理，不作为设备实测温度"
            )
            if pending_new:
                message += "；刚来的锅温日志仍待确认，本次未采用"
            if no_time_new:
                message += "；另有锅温日志缺少测量时间，不能当作实测合格"
            return proof, message, self._reconcile(pot, proof)

        reconcile = self._reconcile(pot, None)
        if pending_new:
            return None, "需要先确认刚来的锅温日志，确认后才能形成实测合格凭据", reconcile
        if no_time_new:
            return None, "锅温日志缺少实际测量时间，不能当作实测合格，无法出证", reconcile
        if usable_new and not allow_new:
            return None, "已回滚到旧环境，只受理旧版锅温设定凭据，不接受新格式单独出证", reconcile
        return None, "该锅既没有已确认的旧锅温设定，也没有确认过的实测锅温日志，无法出证", reconcile

    def _create_proof(self, pot: str, basis: dict[str, Any], version: str) -> dict[str, Any]:
        fixing = self._fixing_of_log(basis)
        if version == LEGACY_VERSION:
            temp = basis.get("锅温设定")
            measure_time = ""
            measured = False
        else:
            temp = basis.get("实测锅温")
            measure_time = basis.get("测温时间", "")
            measured = True
        proof = {
            "id": store.next_pan_id("proof"),
            "证明编号": f"PROOF-{store.pan_state['seq']['proof']:04d}",
            "锅号": pot,
            "杀青记录ID": basis.get("杀青记录ID"),
            "批次号": basis.get("批次号", ""),
            "来源": basis.get("来源"),
            "凭据版本": version,
            "依据日志ID": basis.get("id"),
            "依据日志编号": basis.get("日志编号"),
            "温度": temp,
            "测温时间": measure_time,
            "实测": measured,
            "出料重量": (
                (fixing or {}).get("产出重量")
                or basis.get("出料重量")
                or (fixing or {}).get("上游重量", "")
            ),
            "状态": "有效",
            "接料凭据ID": None,
            "建立时间": datetime.now().isoformat(timespec="seconds"),
        }
        store.pan_proofs.append(proof)
        store.log_event("pan", int(proof["id"]), "issue_proof",
                        {"锅号": pot, "版本": version, "日志": basis.get("日志编号")})
        return proof

    def get_proof(self, pot: str) -> dict[str, Any]:
        # 查询即出证：第一次查证明时就为该锅建立唯一有效证明，之后一直沿用。
        proof, _message, _reconcile = self.ensure_proof(pot)
        sources = self._sources_summary(pot)
        return {
            "锅号": pot,
            "有效证明": proof,
            "告知来源": sources,
            "核对": self._reconcile(pot, proof),
        }

    # ── 揉捻接料 ──

    def _receipt_for_pot(self, pot: str) -> dict[str, Any] | None:
        return next((r for r in store.pan_receipts if r.get("锅号") == pot), None)

    def _receipt_for_rolling(self, rolling_id: int, pot: str) -> dict[str, Any] | None:
        for receipt in store.pan_receipts:
            if receipt.get("锅号") == pot and int(receipt.get("揉捻记录ID", 0)) == rolling_id:
                return receipt
        return None

    def receive(self, rolling_id: int, pot: str,
                request_id: str = "") -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
        """揉捻工位查证明并完成接料；重复接料不重复扣料。"""
        rolling = store.find("rolling", rolling_id)
        if rolling is None:
            return None, f"揉捻记录 {rolling_id} 不存在", {}
        if rolling.get("status") == "已撤回":
            return None, f"揉捻记录 {rolling_id} 已撤回，不能接料", {}

        # 同一锅只能有一份有效接料凭据：重复进入/重复提交都返回原接料记录。
        existing = self._receipt_for_pot(pot)
        if existing is not None:
            reconcile = self._reconcile(pot, self._effective_proof(pot))
            other = int(existing.get("揉捻记录ID", 0))
            if other != rolling_id:
                return existing, (
                    f"该锅已由揉捻记录 {other} 接料（{existing['凭据版本']}，"
                    f"接料凭据 {existing['凭据编号']}），不重复扣料"
                ), reconcile
            return existing, (
                f"揉捻记录 {rolling_id} 已接料（{existing['凭据版本']}，"
                f"接料凭据 {existing['凭据编号']}），不重复扣料"
            ), reconcile

        proof, message, reconcile = self.ensure_proof(pot)
        if proof is None:
            return None, f"无法接料：{message}", reconcile
        if proof.get("凭据版本") == NEW_VERSION and not proof.get("实测"):
            return None, "新版锅温日志缺少实测依据，不能作为接料凭据", reconcile

        # 扣料只发生一次；扣料前结存来自杀青出料重量。
        weight_source = proof.get("出料重量") or rolling.get("上游重量", 0)
        if not weight_source and proof.get("杀青记录ID"):
            fixing_row = store.find("fixing", int(proof["杀青记录ID"]))
            if fixing_row is not None:
                weight_source = fixing_row.get("产出重量") or fixing_row.get("投叶量", 0)
        # 样例数据里重量字段可能是占位文本；解析不出就记为未计量，避免把未知当扣料数。
        try:
            weight = float(str(weight_source).replace("kg", "").replace("斤", "").strip())
        except (TypeError, ValueError):
            weight = None
        if proof.get("出料重量") and weight is None:
            weight_source = proof.get("出料重量")
            try:
                weight = float(str(weight_source).replace("kg", "").replace("斤", "").strip())
            except (TypeError, ValueError):
                weight = None
        receipt = {
            "id": store.next_pan_id("receipt"),
            "凭据编号": f"RECEIPT-{store.pan_state['seq']['receipt']:04d}",
            "证明ID": proof["id"],
            "证明编号": proof["证明编号"],
            "锅号": pot,
            "揉捻记录ID": rolling_id,
            "凭据版本": proof.get("凭据版本"),
            "来源": proof.get("来源"),
            "温度": proof.get("温度"),
            "测温时间": proof.get("测温时间"),
            "接料时间": datetime.now().isoformat(timespec="seconds"),
            "接料重量": weight,
            "扣料前结存": weight,
            "扣料后结存": 0,
            "扣料": bool(weight and weight > 0),
            "request_id": request_id,
            "状态": "已接料",
        }
        store.pan_receipts.append(receipt)
        proof["状态"] = "已使用"
        proof["接料凭据ID"] = receipt["id"]
        proof["接料揉捻记录ID"] = rolling_id

        # 只写一次接料账：重复请求不会再进入这段逻辑。
        rolling["接料已扣料"] = True
        rolling["接料凭据编号"] = receipt["凭据编号"]
        rolling["接料凭据版本"] = receipt["凭据版本"]
        rolling["接料锅号"] = pot
        # 接料办成即视为该揉捻记录已确认（与「完成接料」动作的目标状态一致）。
        if rolling.get("status") in ("草稿", "待确认"):
            rolling["status"] = "已确认"
            rolling["pending"] = False
        if weight and weight > 0:
            rolling["上游重量"] = weight
            debris = store.parse_weight(rolling.get("碎茶比例", "0")) / 100.0
            rolling["产出重量"] = round(weight * (1.0 - debris), 3)

        store.log_event("rolling", rolling_id, "receive",
                        {"锅号": pot, "proof": proof["证明编号"],
                         "version": receipt["凭据版本"], "weight": weight})
        weight_text = f"{weight}kg" if weight is not None else "未计量重量"
        return receipt, (
            f"揉捻记录 {rolling_id} 已按{receipt['凭据版本']}接料 {weight_text}，"
            f"使用接料凭据 {receipt['凭据编号']}"
        ), reconcile

    def receipts_for_rolling(self, rolling_id: int) -> list[dict[str, Any]]:
        """回滚后仍可查：已办成的接料保留当时所用凭据版本。"""
        return [
            dict(r) for r in store.pan_receipts
            if int(r.get("揉捻记录ID", 0)) == int(rolling_id)
        ]

    def receipt_for_rolling(self, rolling_id: int) -> dict[str, Any] | None:
        receipts = self.receipts_for_rolling(rolling_id)
        return receipts[0] if receipts else None

    # ── 切换 / 回滚 ──

    def set_mode(self, mode: str) -> tuple[dict[str, Any], str]:
        normalized = str(mode or "").strip().lower()
        if normalized in ("legacy", "old", "回滚", "旧版"):
            normalized = "legacy"
        elif normalized in ("new", "升级", "新版"):
            normalized = "new"
        else:
            raise ValueError("mode 只能是 new 或 legacy")
        store.pan_state["mode"] = normalized
        if normalized == "legacy":
            store.pan_state["rollback_at"] = datetime.now().isoformat(timespec="seconds")
        else:
            store.pan_state["rollback_at"] = None
        store.log_event("pan", 0, "mode", {"mode": normalized})
        message = (
            "已回滚到旧版锅温设定口径：新的接料只受理旧凭据，已办成的接料保留原凭据历史"
            if normalized == "legacy"
            else "已切换到新版锅温日志口径"
        )
        return self.state(), message

    def state(self) -> dict[str, Any]:
        return {
            "mode": store.pan_state.get("mode", "new"),
            "rollback_at": store.pan_state.get("rollback_at"),
            "logs": len(store.pan_logs),
            "legacy_logs": len(store.pan_legacy_logs),
            "proofs": len([p for p in store.pan_proofs
                           if p.get("状态") in ("有效", "已使用")]),
            "receipts": len(store.pan_receipts),
        }

    # ── 待办与旧记录可查 ──

    def pending_receiving(self) -> list[dict[str, Any]]:
        """还没办成接料的杀青锅，回切后继续可查（含来源与证明状态）。"""
        # 先把旧环境里的锅温设定补登记成告知来源，避免把「还没迁移」误报成没凭据。
        for row in store.rows("fixing"):
            if str(row.get("锅温设定") or "").strip() and not self._logs_for_pot(
                    self.pot_key_for_fixing(row)):
                self.migrate_legacy([int(row.get("id", 0))])
        result: list[dict[str, Any]] = []
        for row in store.rows("fixing"):
            pot = self.pot_key_for_fixing(row)
            if self._receipt_for_pot(pot) is not None:
                continue
            proof = self._effective_proof(pot)
            result.append({
                "杀青记录ID": int(row.get("id", 0)),
                "锅号": pot,
                "批次号": row.get("批次号", ""),
                "status": row.get("status", ""),
                "锅温设定": row.get("锅温设定", ""),
                "出料重量": row.get("产出重量", row.get("出料重量", "")),
                "告知来源": self._sources_summary(pot),
                "有效证明": proof,
                "核对": self._reconcile(pot, proof),
            })
        return result


pan_service = PanService()
