import os
from collections.abc import Iterable
from pathlib import Path

# 版本信息
__version__ = '2.5-alpha'

# 项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# 客户端配置
class ClientConfig:
    addr = '100.97.117.78'      # Server 地址
    port = '6016'               # Server 端口

    # 快捷键配置列表
    shortcuts = [
        # 所有快捷键均由 Hammerspoon 监听并发送 UDP 触发，绕过 pynput 在 macOS 上的限制
        # {'key': 'middle', 'type': 'mouse', 'suppress': True, 'hold_mode': True, 'enabled': True, 'mouse_button': 'x2'},
        # {'key': 'f5', 'type': 'keyboard', 'suppress': True, 'hold_mode': True, 'enabled': True},
    ]

    threshold    = 0.3          # 快捷键触发阈值（秒）

    paste        = False        # 是否以写入剪切板然后模拟 Ctrl-V 粘贴的方式输出结果
    restore_clip = False        # 模拟粘贴后是否恢复剪贴板
    switch_input_method = True   # 打字输出前是否自动切换到英文输入法（macOS 使用 util/tools/switch_input 精确切换，失败回退粘贴），输入完成后恢复

    save_transcript = True      # 是否保存转录文本和时间到本地日记文件 (YYYY/MM/DD.md)
    save_audio = True          # 是否保存录音文件
    save_audio_limit = 0       # 最多保留多少条录音文件（用于排查错误，0 表示不限制）
    audio_name_len = 20         # 将录音识别结果的前多少个字存储到录音文件名中，建议不要超过200
    
    context = ''                # 提示词上下文，用于辅助 Fun-ASR-Nano 模型识别（例如输入人名、地名、专业术语等）

    trash_punc = '，。,.'       # 识别结果要消除的末尾标点

    traditional_convert = False     # 是否将识别结果转换为繁体中文
    traditional_locale = 'zh-hant'  # 繁体地区：'zh-hant'（标准繁体）, 'zh-tw'（台湾繁体）, 'zh-hk'（香港繁体）

    hot = True                 # 是否启用热词替换（统一 RAG 匹配）
    hot_thresh = 0.85           # RAG 替换热词阈值（高阈值，用于实际替换）
    hot_similar = 0.6           # RAG 相似热词阈值（低阈值，用于 LLM 上下文）
    hot_rectify = 0.6           # 纠错历史 RAG 匹配阈值（低阈值，用于 LLM 上下文）
    hot_rule = True             # 是否启用自定义规则替换（基于正则表达式）

    llm_enabled = True          # 是否启用 LLM 润色功能，需要配置 LLM/ 目录下的角色文件
    llm_stop_key = 'esc'        # 中断 LLM 输出的快捷键（llm_enabled=False 时不注册）

    enable_tray = True          # 客户端默认启用托盘图标功能

    # 日志配置
    log_level = 'INFO'          # 日志级别：'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'

    audio_gain = 20.0            # 全局默认固定增益系数（1.0=原样，>1.0=放大，<1.0=衰减）
    audio_normalize = False      # 是否启用峰值归一化（自动将每段音频的最大振幅调整到接近满幅但不过曝）。启用时会忽略 audio_gain 的固定值
    audio_normalize_target = 0.95  # 峰值归一化的目标振幅（建议 0.9~0.99，留一点 headroom 防止削波）

    # 自适应响度补偿（AGC）：按每块音频的平均电平（RMS）自动调整增益，推荐开启。
    # 启用后忽略 audio_gain、mic_devices 里的 gain、default_device_gain 等固定增益。
    # 优先级：audio_agc > audio_normalize > 固定增益。
    audio_agc = True                # 是否启用自适应响度补偿
    audio_agc_target_db = -20.0     # 目标平均电平（dBFS RMS），-20 约等于满幅的 10%，-18~-24 都合适
    audio_agc_max_gain_db = 30.0    # 最大放大 30dB（约 31.6 倍），防止把底噪一起抬上来
    audio_agc_min_gain_db = -12.0   # 最大衰减 12dB（约 0.25 倍），防止大音量爆音
    audio_agc_gate_db = -55.0       # 静音门限：低于此电平的块只沿用当前增益、不更新增益
    audio_agc_attack = 0.15         # 增益下降的时间常数（秒），越小越能压住突然的爆音
    audio_agc_release = 2.5         # 增益回升的时间常数（秒），越大音量越稳、适应越慢

    # 按麦克风设备名称（部分匹配）单独设置增益，优先级高于 audio_gain。
    # 键为设备名称片段（不区分大小写），值为增益系数。
    # 找不到匹配时使用 audio_gain 作为回退。
    mic_device_gains = {
        # 'DJI Mic Mini': 25.0,
        # 'Wireless Mic Rx': 15.0,
    }

    mic_seg_duration = 60       # 麦克风听写时分段长度：60秒
    mic_seg_overlap = 4         # 麦克风听写时分段重叠：4秒

    file_seg_duration = 60      # 转录文件时分段长度
    file_seg_overlap = 4        # 转录文件时分段重叠

    file_save_srt = True        # 转录文件时是否保存 srt 字幕
    file_save_txt = True        # 转录文件时是否保存 txt 文本（按标点切分后的）
    file_save_json = True       # 转录文件时是否保存 json 结果（含原始时间戳）
    file_save_merge = False      # 转录文件时是否保存 merge.txt（未切分的段落长文本）

    udp_broadcast = True                # 是否启用 UDP 广播输出结果
    udp_broadcast_targets = [           # UDP 广播目标地址列表，格式: (地址, 端口)
        ('127.255.255.255', 6017),      # 本地回环广播
        # ('192.168.1.255', 6017),      # 局域网广播（示例，按需启用）
    ]

    udp_control = True              # 是否启用 UDP 控制录音（外部程序发送 START/STOP 命令）
    udp_control_addr = '127.0.0.1'  # UDP 控制监听地址（'0.0.0.0' 允许外部访问）
    udp_control_port = 6018         # UDP 控制监听端口

    udp_status_target = ('127.0.0.1', 6019)  # 处理状态回传目标（Hammerspoon 等外部工具监听端口），设为 None 则禁用

    idle_exit_enabled = True        # 是否启用空闲自动释放麦克风
    idle_timeout = 10               # 空闲超时时间（秒），超过此时间无操作则释放麦克风
    idle_check_interval = 1         # 空闲检查间隔（秒），建议设为 1~5 秒

    # WebSocket 连接配置（对 SSH 隧道等不稳定网络尤为重要）
    ws_connect_timeout = 10         # WebSocket 连接超时（秒）
    ws_ping_interval = 20           # WebSocket 心跳发送间隔（秒），0 表示禁用
    ws_ping_timeout = 10            # WebSocket 心跳响应超时（秒）
    ws_retry_delay = 2.0            # 每次重试之间的等待时间（秒），给 autossh 等隧道恢复留出时间
    ws_max_retries = 5              # 连接失败时的最大重试次数

    # 麦克风设备配置（顺位 + 增益一体化）
    # 列表顺序即为查找优先级；每个条目包含设备名称片段和专属增益。
    # 找不到匹配时自动回落到系统默认麦克风，并使用全局 audio_gain。
    mic_devices = [
        {'name': 'Wireless Mic Rx', 'gain': 20.0},
        # {'name': 'DJI Mic Mini 2-6D85A5', 'gain': 21.0},
        # AirPods 自身的麦克风电平就很高（戴在耳朵上时接近满幅），增益必须调小，否则削波
        {'name': 'AirPods Pro 2', 'gain': 4.0},
    ]

    default_device_gain = 2   # 回退到系统默认麦克风时的专属增益（None 则使用全局 audio_gain）

    # 兼容旧版分开配置（仅在 mic_devices 为空时生效）
    # mic_device_names = ['Wireless Mic Rx', 'DJI Mic Mini 2-6D85A5' ]  # 优先使用的麦克风名称列表（部分匹配），按顺序查找
    # 兼容旧版单字符串配置：mic_device_name = 'Wireless Mic Rx'


    # 兼容旧版增益字典（仅在 mic_devices 为空时生效）
    mic_device_gains = {
        # 'DJI Mic Mini': 25.0,
        # 'Wireless Mic Rx': 15.0,
    }

    # 语音命令配置
    # 当识别结果匹配到对应正则时，执行指定动作，而不是输出文本
    # action 目前仅支持 'open'：打开网址或应用程序
    # target 可以是网址 (https://...) 或本地路径
    voice_commands = [
        # 示例：打开网页
        # {'pattern': r'打开\s*It\s*之家', 'action': 'open', 'target': 'https://www.ithome.com'},
        # {'pattern': r'打开\s*GitHub',   'action': 'open', 'target': 'https://github.com'},
        # 示例：打开应用（macOS）
        # {'pattern': r'打开\s*微信',     'action': 'open', 'target': '/Applications/WeChat.app'},
        # 示例：打开应用（Windows）
        # {'pattern': r'打开\s*记事本',   'action': 'open', 'target': 'notepad'},
    ]


# 快捷键配置说明
r"""
快捷键配置字段说明：
  key        - 按键名称（见下方可用按键列表）
  type       - 输入类型：'keyboard'（键盘）或 'mouse'（鼠标）
  suppress   - 是否阻塞按键（True=阻塞，False=不阻塞）
  hold_mode  - 长按模式（True=按下录音松开停止，False=单击开始再次单击停止）
  enabled    - 是否启用此快捷键

阻塞模式说明：
  - 阻塞模式  ：长按录音识别，短按（<0.3秒）则自动补发按键，不影响单击功能
  - 非阻塞模式：对于 CapsLock/NumLock/ScrollLock 这类切换键，松开时会自动补发，以恢复按键状态

可用按键名称：

  字母数字：a - z, 0 - 9（大键盘）, numpad0 - numpad9（小键盘）

  符号键：, . / \ ` ' - = [ ] ; '

  小键盘：
      decimal(小数点), numpad_add(+), numpad_subtract(-),
      numpad_multiply(*), numpad_divide(/), numpad_enter

  功能键：f1 - f24

  控制键:
      ctrl,   ctrl_r,
      shift,  shift_r,
      alt,    alt_r,
      cmd,    cmd_r

  特殊键：
      space, enter, tab, backspace, delete, insert, home, end
      page_up, page_down, esc, caps_lock, num_lock, scroll_lock
      print_screen, pause, menu

  方向键：up, down, left, right

  鼠标键：x1, x2

示例配置：
  {'key': 'caps_lock', 'type': 'keyboard', 'suppress': False, 'hold_mode': True, 'enabled': True}, 
  {'key': 'f12', 'type': 'keyboard', 'suppress': True, 'hold_mode': True, 'enabled': True}, 
  {'key': 'x2', 'type': 'mouse', 'suppress': True, 'hold_mode': True, 'enabled': True}, 
"""

