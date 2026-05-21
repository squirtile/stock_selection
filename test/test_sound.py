# test_sound.py
import time

try:
    import winsound
except ImportError:
    winsound = None


def play_buy_point_sound(times: int = 3):
    """
    测试分钟级B点提示音。
    Windows 使用 winsound.Beep；
    非 Windows 系统使用终端响铃符。
    """
    for i in range(max(1, int(times))):
        try:
            if winsound is not None:
                print(f"播放第 {i + 1} 声...")
                winsound.Beep(1200, 260)
                time.sleep(0.08)
            else:
                print("\a", end="", flush=True)
                time.sleep(0.3)
        except Exception as e:
            print(f"播放声音失败：{e}")


if __name__ == "__main__":
    print("开始测试提示音...")
    play_buy_point_sound(times=3)
    print("测试完成。")