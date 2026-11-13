
import pynvml
import time

# 初始化 NVIDIA 监控接口
pynvml.nvmlInit()

try:
    gpu = pynvml.nvmlDeviceGetHandleByIndex(0)

    print("LagLens GPU Monitor")
    print("按 Ctrl+C 停止监控\n")

    while True:
        # 获取显卡实时数据
        usage = pynvml.nvmlDeviceGetUtilizationRates(gpu)
        memory = pynvml.nvmlDeviceGetMemoryInfo(gpu)
        temperature = pynvml.nvmlDeviceGetTemperature(
            gpu, pynvml.NVML_TEMPERATURE_GPU
        )

        # 显示监控数据
        print(
            f"GPU: {usage.gpu}% | "
            f"VRAM: {memory.used / 1024**2:.0f} MiB | "
            f"Temp: {temperature}°C"
        )

        # 等待一秒钟
        time.sleep(1)

except KeyboardInterrupt:
    print("\n监控已停止")

finally:
    pynvml.nvmlShutdown()
