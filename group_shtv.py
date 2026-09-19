#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
M3U 频道分组与去重处理脚本 (针对 shtv.m3u)
1. 读取 M3U 文件 (默认: ./shtv.m3u)
2. 过滤/删除购物类视频源
3. 将视频源划分为: 高清、标清、4K
4. 对标清分组进行去重判断，若已存在于高清分组中，则从标清分组中剔除
5. 填充并更新 group-title 参数
6. 按照 高清 -> 标清 -> 4K 的顺序输出 (默认: ./shtv.m3u)
"""

import argparse
import os
import re
import sys
from typing import Dict, List, Set, Tuple


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
    - 高清: 包含 HD, 高清, 1080 (且非 4K)
    - 标清: 其余普通/标清频道
    """
    m_name = re.search(r'tvg-name="([^"]*)"', extinf_line, re.IGNORECASE)
    tvg_name = m_name.group(1) if m_name else ""

    comma_idx = extinf_line.rfind(",")
    title = extinf_line[comma_idx + 1:].strip() if comma_idx != -1 else ""

    check_text = f"{tvg_name} {title}".upper()

    # 1. 判断 4K/超高清
    if re.search(r"(?:4K|8K|UHD|超高清)", check_text):
        return "4K"

    # 2. 判断 高清/HD
    if re.search(r"(?:HD|高清|1080)", check_text):
        return "高清"

    # 3. 默认标清频道
    return "标清"


def normalize_channel_name(name: str) -> str:
    """
    规范化频道名称，用于比对高清与标清分组中的频道重复性:
    1. 别名归一化 (如 卡酷卡通 -> 卡酷少儿)
    2. 去除清晰度标签 (HD, 高清, 标清, 超清, 1080P 等)
    3. 去除连字符、下划线、空格等非关键符号并转大写
    """
    alias_map = {
        "卡酷卡通": "卡酷少儿",
    }
    for k, v in alias_map.items():
        if k in name:
            name = name.replace(k, v)

    name = re.sub(r"(?i)HD|高清|超清|标清|1080[PI]?", "", name)
    name = re.sub(r"[\s\-_]+", "", name)
    return name.upper()


def get_channel_keys(extinf_line: str) -> Tuple[str, str]:
    """
    提取并归一化 EXTINF 行中的 (tvg-name, title)
    """
    m_name = re.search(r'tvg-name="([^"]*)"', extinf_line, re.IGNORECASE)
    tvg_name = m_name.group(1) if m_name else ""

    comma_idx = extinf_line.rfind(",")
    title = extinf_line[comma_idx + 1:].strip() if comma_idx != -1 else ""

    return normalize_channel_name(tvg_name), normalize_channel_name(title)


def update_group_title(extinf_line: str, group: str) -> str:
    """
    更新或添加 EXTINF 行中的 group-title 参数
    """
    if re.search(r'group-title="[^"]*"', extinf_line):
        return re.sub(r'group-title="[^"]*"', f'group-title="{group}"', extinf_line)
    elif re.search(r"group-title='[^']*'", extinf_line):
        return re.sub(r"group-title='[^']*'", f"group-title='{group}'", extinf_line)
    elif re.search(r'group-title=[^\s,]+', extinf_line):
        return re.sub(r'group-title=[^\s,]+', f'group-title="{group}"', extinf_line)

    comma_idx = extinf_line.rfind(",")
    if comma_idx != -1:
        return f'{extinf_line[:comma_idx]} group-title="{group}"{extinf_line[comma_idx:]}'

    return f'{extinf_line} group-title="{group}"'


def process_m3u(
    input_path: str,
    output_path: str,
    reorder_by_group: bool = True,
    filter_shopping: bool = True,
    dedup_sd: bool = True
) -> None:
    """
    解析 input_path，过滤购物频道，分类并对标清频道去重，更新 group-title，写入 output_path
    """
    if not os.path.exists(input_path):
        print(f"错误: 输入文件不存在: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    header_lines: List[str] = []
    raw_channels: List[Tuple[str, List[str]]] = []
    removed_shopping: List[str] = []

    current_entry: List[str] = []
    has_started_channels = False

    def add_channel_entry(entry_lines: List[str]) -> None:
        if not entry_lines:
            return
        extinf = entry_lines[0]
        comma_idx = extinf.rfind(",")
        title = extinf[comma_idx + 1:].strip() if comma_idx != -1 else extinf

        # 过滤购物频道
        if filter_shopping and is_shopping_channel(extinf):
            removed_shopping.append(title)
            return

        cat = classify_channel(extinf)
        raw_channels.append((cat, entry_lines))

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

    # 1. 提取所有高清频道的特征键集合
    hd_keys: Set[str] = set()
    for cat, entry_lines in raw_channels:
        if cat == "高清":
            k_tvg, k_title = get_channel_keys(entry_lines[0])
            if k_tvg:
                hd_keys.add(k_tvg)
            if k_title:
                hd_keys.add(k_title)

    # 2. 分组并去重标清频道
    grouped_channels: Dict[str, List[List[str]]] = {
        "高清": [],
        "标清": [],
        "4K": []
    }
    removed_duplicates: List[str] = []
    final_channels: List[Tuple[str, List[str]]] = []

    for cat, entry_lines in raw_channels:
        extinf = entry_lines[0]
        comma_idx = extinf.rfind(",")
        title = extinf[comma_idx + 1:].strip() if comma_idx != -1 else extinf

        # 标清分组去重判断：如果已在高清分组中出现过，则删除
        if cat == "标清" and dedup_sd:
            k_tvg, k_title = get_channel_keys(extinf)
            if (k_tvg and k_tvg in hd_keys) or (k_title and k_title in hd_keys):
                removed_duplicates.append(title)
                continue

        # 更新 group-title
        entry_lines[0] = update_group_title(extinf, cat)
        grouped_channels[cat].append(entry_lines)
        final_channels.append((cat, entry_lines))

    # 输出统计信息
    total_parsed = len(raw_channels) + len(removed_shopping)
    print(f"解析完成，原始视频源共 {total_parsed} 个:")
    if filter_shopping and removed_shopping:
        print(f"  - 已过滤购物频道: {len(removed_shopping)} 个: {', '.join(removed_shopping)}")
    if dedup_sd and removed_duplicates:
        print(f"  - 标清分组中已剔除高清重复项: {len(removed_duplicates)} 个")
        print(f"    (例如: {', '.join(removed_duplicates[:8])}...)")
    print(f"  - 最终保留视频源: {len(final_channels)} 个")
    print(f"      * 高清: {len(grouped_channels['高清'])} 个")
    print(f"      * 标清: {len(grouped_channels['标清'])} 个")
    print(f"      * 4K  : {len(grouped_channels['4K'])} 个")

    # 写入输出文件
    output_lines: List[str] = []
    if header_lines:
        output_lines.extend(header_lines)
    else:
        output_lines.append('#EXTM3U')

    if reorder_by_group:
        # 按照 高清 -> 标清 -> 4K 顺序输出
        for group_name in ["高清", "标清", "4K"]:
            for entry in grouped_channels[group_name]:
                output_lines.extend(entry)
    else:
        # 保持原有相对顺序
        for _, entry in final_channels:
            output_lines.extend(entry)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines) + "\n")

    print(f"已成功将修改后的内容输出到: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="将 M3U 直播源按 高清、标清、4K 分类，去重标清并填充 group-title"
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
        help="保持原有顺序（默认按 高清 -> 标清 -> 4K 聚类排列）"
    )
    parser.add_argument(
        "--keep-shopping",
        action="store_true",
        help="保留购物频道（默认会自动过滤删除购物频道）"
    )
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="不剔除标清分组中已存在于高清的重复频道"
    )

    args = parser.parse_args()
    process_m3u(
        args.input,
        args.output,
        reorder_by_group=not args.no_reorder,
        filter_shopping=not args.keep_shopping,
        dedup_sd=not args.no_dedup
    )


if __name__ == "__main__":
    main()
