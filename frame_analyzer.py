
import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

import frame_timebase


# CSV 文件位置
CSV_FILE = Path(__file__).with_name("sample_capture.csv")


def percentile(values, percent):
    """计算帧时间百分位数"""
    values = sorted(values)
    index = math.ceil(len(values) * percent / 100) - 1
    return values[max(0, index)]


def analyze_frames():
    if not CSV_FILE.exists():
        print(f"找不到文件: {CSV_FILE}")
        return

    # 读取 PresentMon 数据
    with CSV_FILE.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        rows = list(csv.DictReader(file))

    if not rows:
        print("CSV 文件没有帧记录")
        return

    timebase = frame_timebase.resolve_timebase(
        rows[0].keys(),
        csv_path=CSV_FILE,
    )

    # 不混合不同进程或交换链的数据
    groups = defaultdict(list)

    for row in rows:
        key = (
            row["Application"],
            row["ProcessID"],
            row["SwapChainAddress"],
        )
        groups[key].append(row)

    # 第一版：选择记录最多的交换链
    target = max(groups, key=lambda key: len(groups[key]))
    selected_rows = groups[target]

    frame_times = []
    start_times = []

    for row in selected_rows:
        try:
            frame_time = float(row["FrameTime"])
            start_time = timebase.normalize(
                float(row[timebase.raw_column])
            )

            if (
                math.isfinite(frame_time)
                and frame_time > 0
                and math.isfinite(start_time)
            ):
                frame_times.append(frame_time)
                start_times.append(start_time)

        except (ValueError, TypeError, KeyError):
            continue

    if not frame_times:
        print("没有有效的 FrameTime 数据")
        return

    # 计算统计指标
    average_ms = statistics.mean(frame_times)
    median_ms = statistics.median(frame_times)
    max_ms = max(frame_times)
    p95_ms = percentile(frame_times, 95)

    # 由平均帧间隔换算帧生成速率
    average_fps = 1000 / average_ms

    # 初步异常候选阈值（并非最终卡顿算法）
    threshold = max(50.0, median_ms * 2)
    spikes = [
        value for value in frame_times
        if value > threshold
    ]

    duration = (
        max(start_times) - min(start_times)
    ) / 1000

    # 输出分析报告
    print("\n========== LagLens Frame Analyzer ==========")

    print(f"程序: {target[0]}")
    print(f"进程 ID: {target[1]}")
    print(f"交换链: {target[2]}")
    print(f"CSV 总记录数: {len(rows)}")
    print(f"当前交换链记录数: {len(selected_rows)}")
    print(f"有效帧间隔数: {len(frame_times)}")

    print("\n---------- Frame Performance ----------")

    print(f"记录覆盖时间: {duration:.2f} 秒")
    print(f"平均帧时间: {average_ms:.2f} ms")
    print(f"中位帧时间: {median_ms:.2f} ms")
    print(f"95% 帧时间: {p95_ms:.2f} ms")
    print(f"最大帧时间: {max_ms:.2f} ms")
    print(f"平均帧生成速率估计: {average_fps:.2f} FPS")

    print("\n---------- Spike Detection ----------")

    print(f"异常候选阈值: {threshold:.2f} ms")
    print(f"超过阈值的帧: {len(spikes)}")

    if spikes:
        print("检测到帧时间尖峰候选")
    else:
        print("没有检测到超过阈值的帧")

    print("\n注意：这不是屏幕实际显示 FPS，")
    print("异常候选也不一定代表用户可感知的卡顿。")
    print("============================================\n")


if __name__ == "__main__":
    analyze_frames()
