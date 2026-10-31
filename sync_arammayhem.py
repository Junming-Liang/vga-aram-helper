#!/usr/bin/env python3
"""Sync the optional current-patch pick-rate reference (CC BY 4.0)."""
import argparse
import json
from pathlib import Path

from arammayhem_stats import sync
from update_network import runtime_state_dir


def main():
    parser = argparse.ArgumentParser(
        description='同步 arammayhem.com 当前版本登场率（CC BY 4.0；不含胜率/T 级）')
    parser.add_argument('--state-dir', type=Path,
                        help='缓存目录；默认与助手运行时状态目录一致')
    args = parser.parse_args()
    state_dir = args.state_dir or runtime_state_dir()
    try:
        result = sync(state_dir)
    except Exception as exc:
        parser.exit(1, f'同步失败：{exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
