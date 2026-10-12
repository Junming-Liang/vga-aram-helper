#!/usr/bin/env python3
"""Import authorized JSON only. No downloads, executable code or image assets."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from engine import normalize

PATTERNS = {"heroes": "heroIndex-*.json", "augments": "augments-*.json", "items": "items-*.json", "relations": "relations-*.json", "combinations": "combinations-*.json"}


def import_directory(source, output):
    raw, provenance = {}, []
    for kind, pattern in PATTERNS.items():
        files = list(source.glob(pattern))
        if len(files) != 1:
            raise ValueError(f"{pattern} 需恰好匹配一个文件，当前 {len(files)} 个")
        content = files[0].read_bytes()
        raw[kind] = json.loads(content)
        provenance.append({"filename": files[0].name, "sha256": hashlib.sha256(content).hexdigest()})
    latest = None
    logs = list(source.glob("changelogs-*.json"))
    if len(logs) == 1:
        dates = [entry.get("date") for entry in json.loads(logs[0].read_text(encoding="utf-8")).get("data", []) if isinstance(entry.get("date"), str)]
        latest = max(dates) if dates else None
    raw["metadata"] = {"title": "本地导入的公开参考快照", "isDemo": False, "source": "Huya 公开网页参考数据（桌面客户端数据未验证）",
                       "sourceUrl": "https://gametool.huya.com/lolhex", "latestChangelogDate": latest,
                       "dataFreshness": "unknown", "winRateScope": "源数据公开参考值，样本、统计区间及英雄×海克斯配对胜率未提供",
                       "importedAt": datetime.now(timezone.utc).isoformat(), "files": provenance,
                       "licenseNote": "仅限用户授权的本地研究。公开可访问不等于可再分发；交付包不包含这些数据。"}
    data = normalize(raw)
    # A failed or repeated import must not destroy an existing local dataset.
    with output.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return {kind: len(data[kind]) for kind in PATTERNS}


def main():
    parser = argparse.ArgumentParser(description="从您有权使用的公开 JSON 快照导入文本字段（不含图片/脚本）")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(import_directory(args.source, args.output), ensure_ascii=False))
    except (OSError, ValueError) as exc:
        parser.exit(1, f"导入失败：{exc}\n")


if __name__ == "__main__":
    main()
