#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
M3U 频道分组与过滤脚本
1. 读取 M3U 文件
2. 过滤/删除购物类视频源
3. 将视频源按照 4K、HD、常规 三类分组，并填充/更新 group-title 参数
4. 输出到指定文件
"""

import argparse
import os
import re
import sys
from typing import Dict, List, Tuple


def is_shopping_channel(extinf_line: str) -> bool:
    """
    判断是否为购物频道
    匹配常见购物关键词：购物、商城、聚鲨、家有购物、风尚购物、快乐购、优品、SHOP等
    """
    m_name = re.search(r'tvg-name="([^"]*)"', extinf_line, re.IGNORECASE)
    tvg_name = m_name.group(1) if m_name else ""

    comma_idx = extinf_line.rfind(",")
    title = extinf_line[comma_idx + 1:].strip() if comma_idx != -1 else ""

    check_text = f"{tvg_name} {title}".upper()
    shopping_pattern = r"(?:购物|商城|聚鲨|家有购物|风尚购物|快乐购|优品|SHOP)"
    return bool(re.search(shopping_pattern, check_text, re.IGNORECASE))


def classify_channel(extinf_line: str) -> str:
    """
    根据 EXTINF 行中的频道名称和 tvg-name 判断清晰度分组:
    - 4K: 包含 4K, 8K, UHD, 超高清
    - HD: 包含 HD, 高清, 1080 (且非 4K)
    - 常规: 其余频道
    """
    # 提取 tvg-name
    m_name = re.search(r'tvg-name="([^"]*)"', extinf_line, re.IGNORECASE)
    tvg_name = m_name.group(1) if m_name else ""

    # 提取逗号后面的频道显示名称
    comma_idx = extinf_line.rfind(",")
    title = extinf_line[comma_idx + 1:].strip() if comma_idx != -1 else ""

    # 组合待检测文本
    check_text = f"{tvg_name} {title}".upper()

    # 1. 判断 4K/超高清
    if re.search(r"(?:4K|8K|UHD|超高清)", check_text):
        return "4K"

    # 2. 判断 HD/高清
    if re.search(r"(?:HD|高清|1080)", check_text):
        return "HD"

    # 3. 默认常规频道
    return "常规"


def update_group_title(extinf_line: str, group: str) -> str:
    """
    更新或添加 EXTINF 行中的 group-title 参数
    """
    # 如果已存在 group-title="..."
    if re.search(r'group-title="[^"]*"', extinf_line):
        return re.sub(r'group-title="[^"]*"', f'group-title="{group}"', extinf_line)

    # 如果已存在 group-title='...'
    if re.search(r"group-title='[^']*'", extinf_line):
        return re.sub(r"group-title='[^']*'", f"group-title='{group}'", extinf_line)

    # 如果已存在 group-title=xxx
    if re.search(r'group-title=[^\s,]+', extinf_line):
        return re.sub(r'group-title=[^\s,]+', f'group-title="{group}"', extinf_line)

    # 如果不存在 group-title，插入在频道标题逗号之前
    comma_idx = extinf_line.rfind(",")
    if comma_idx != -1:
        return f'{extinf_line[:comma_idx]} group-title="{group}"{extinf_line[comma_idx:]}'

    return f'{extinf_line} group-title="{group}"'


def process_m3u(
    input_path: str,
    output_path: str,
    reorder_by_group: bool = True,
    filter_shopping: bool = True
) -> None:
    """
    解析 input_path，过滤购物频道，分类并更新 group-title，写入 output_path
    """
    if not os.path.exists(input_path):
        print(f"错误: 输入文件不存在: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    header_lines: List[str] = []
    # 存储频道条目: (category, [line1, line2, ...])
    channels: List[Tuple[str, List[str]]] = []
    removed_shopping: List[str] = []

    current_entry: List[str] = []
    has_started_channels = False

    def add_channel_entry(entry_lines: List[str]) -> None:
        if not entry_lines:
            return
        extinf = entry_lines[0]
        comma_idx = extinf.rfind(",")
        title = extinf[comma_idx + 1:].strip() if comma_idx != -1 else extinf

        if filter_shopping and is_shopping_channel(extinf):
            removed_shopping.append(title)
            return

        cat = classify_channel(extinf)
        entry_lines[0] = update_group_title(extinf, cat)
        channels.append((cat, entry_lines))

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("#EXTINF"):
            has_started_channels = True
            if current_entry:
                add_channel_entry(current_entry)
            current_entry = [stripped]
        elif not has_started_channels:
            header_lines.append(stripped)
        else:
            if current_entry:
                current_entry.append(stripped)

    # 处理最后一个条目
    if current_entry:
        add_channel_entry(current_entry)

    # 分组统计
    grouped_channels: Dict[str, List[List[str]]] = {
        "4K": [],
        "HD": [],
        "常规": []
    }

    for cat, entry_lines in channels:
        grouped_channels[cat].append(entry_lines)

    # 输出统计信息
    total_retained = len(channels)
    total_parsed = total_retained + len(removed_shopping)
    print(f"解析完成，原始视频源共 {total_parsed} 个:")
    if filter_shopping:
        print(f"  - 已过滤购物频道: {len(removed_shopping)} 个: {', '.join(removed_shopping)}")
    print(f"  - 最终保留视频源: {total_retained} 个")
    print(f"      * 4K  : {len(grouped_channels['4K'])} 个")
    print(f"      * HD  : {len(grouped_channels['HD'])} 个")
    print(f"      * 常规: {len(grouped_channels['常规'])} 个")

    # 写入输出文件
    output_lines: List[str] = []
    if header_lines:
        output_lines.extend(header_lines)
    else:
        output_lines.append('#EXTM3U')

    if reorder_by_group:
        # 按 4K -> HD -> 常规 顺序输出
        for group_name in ["4K", "HD", "常规"]:
            for entry in grouped_channels[group_name]:
                output_lines.extend(entry)
    else:
        # 保持原有相对顺序
        for _, entry in channels:
            output_lines.extend(entry)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines) + "\n")

    print(f"已成功将修改后的内容输出到: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="将 M3U 直播源按 4K、HD、常规 分类并填充 group-title，支持过滤购物频道"
    )
    parser.add_argument(
        "-i", "--input",
        default="./shtv.m3u",
        help="输入 M3U 文件路径 (默认: ./shtv.m3u)"
    )
    parser.add_argument(
        "-o", "--output",
        default="./shtv.m3u",
        help="输出 M3U 文件路径 (默认: ./shtv.m3u)"
    )
    parser.add_argument(
        "--no-reorder",
        action="store_true",
        help="是否保持原有顺序（默认会将同分组频道聚类排列）"
    )
    parser.add_argument(
        "--keep-shopping",
        action="store_true",
        help="保留购物频道（默认会自动过滤删除购物频道）"
    )

    args = parser.parse_args()
    process_m3u(
        args.input,
        args.output,
        reorder_by_group=not args.no_reorder,
        filter_shopping=not args.keep_shopping
    )


if __name__ == "__main__":
    main()
