# coding: utf-8
"""
Python 配置文件加载工具

提供统一的 Python 格式配置文件加载、迁移和 UI 追加功能。
"""

import importlib.util
import re
from pathlib import Path
from typing import Any, List, Dict, Tuple, Optional


def load_py_config(path: Path, var_name: str) -> Any:
    """
    动态加载 .py 配置文件中的指定变量。

    Args:
        path: 配置文件路径
        var_name: 要读取的变量名

    Returns:
        变量值，如果文件不存在或变量不存在则返回 None
    """
    if not path.exists():
        return None

    # 使用唯一模块名，避免污染 sys.modules
    module_name = f"_capswriter_cfg_{path.stem}_{id(path)}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, var_name, None)


def _split_rule_line(line: str) -> Tuple[str, str]:
    """
    分割规则行，优先找右侧前面有空格的 '='。
    """
    for i in range(len(line) - 1, -1, -1):
        if line[i] == '=':
            if i > 0 and line[i - 1].isspace():
                return line[:i].strip(), line[i + 1:].strip()
    parts = line.split('=', 1)
    return parts[0].strip(), parts[1].strip() if len(parts) > 1 else ''


def _migrate_hotwords(txt_path: Path) -> List[str]:
    """从旧 hot.txt 迁移热词列表"""
    with open(txt_path, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]


def _migrate_rules(txt_path: Path) -> List[Tuple[str, str]]:
    """从旧 hot-rule.txt 迁移规则列表"""
    rules = []
    with open(txt_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line or line.startswith('#'):
                continue
            pattern, replacement = _split_rule_line(line)
            if pattern:
                rules.append((pattern, replacement))
    return rules


def _migrate_rectifications(txt_path: Path) -> List[Dict[str, str]]:
    """从旧 hot-rectify.txt 迁移纠错记录"""
    with open(txt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    records = []
    for block in content.split('---'):
        lines = [l.strip() for l in block.split('\n') if l.strip() and not l.strip().startswith('#')]
        if len(lines) >= 2:
            records.append({"wrong": lines[0], "right": lines[1]})
    return records


def migrate_txt_to_py(txt_path: Path, py_path: Path, config_type: str) -> bool:
    """
    自动将旧 TXT 配置文件迁移为新的 .py 配置文件。

    Args:
        txt_path: 旧 TXT 文件路径
        py_path: 新 .py 文件路径
        config_type: 配置类型，可选 'hotwords', 'rules', 'rectifications', 'server_hotwords'

    Returns:
        是否成功迁移
    """
    if not txt_path.exists():
        return False
    if py_path.exists():
        return True  # 已存在，不需要迁移

    py_path.parent.mkdir(parents=True, exist_ok=True)

    if config_type in ('hotwords', 'server_hotwords'):
        items = _migrate_hotwords(txt_path)
        var_name = 'HOTWORDS'
        header = '# 热词配置\n# 以 # 开头的行为注释，会被忽略\n\n'
        body = f'{var_name} = [\n' + ''.join(f'    {repr(item)},\n' for item in items) + ']\n'
    elif config_type == 'rules':
        items = _migrate_rules(txt_path)
        var_name = 'RULES'
        header = '# 规则替换配置\n# 每个元组: (正则模式, 替换文本)\n# 替换文本为空字符串 "" 表示删除匹配内容\n\n'
        body = f'{var_name} = [\n'
        for pattern, replacement in items:
            p_str = repr(pattern)
            r_str = repr(replacement)
            body += f'    ({p_str}, {r_str}),\n'
        body += ']\n'
    elif config_type == 'rectifications':
        items = _migrate_rectifications(txt_path)
        var_name = 'RECTIFICATIONS'
        header = '# 纠错历史配置\n# 每条记录是一个字典，包含 "wrong" 和 "right"\n\n'
        body = f'{var_name} = [\n'
        for rec in items:
            body += '    {\n'
            body += f'        "wrong": {repr(rec["wrong"])},\n'
            body += f'        "right": {repr(rec["right"])},\n'
            body += '    },\n'
        body += ']\n'
    else:
        return False

    py_path.write_text(header + body, encoding='utf-8')
    return True


def append_to_py_list(py_path: Path, var_name: str, value: Any) -> None:
    """
    向 .py 配置文件末尾追加一条 `var_name.append(value)` 语句。

    Args:
        py_path: 配置文件路径
        var_name: 列表变量名
        value: 要追加的值（会被 repr 序列化）
    """
    if not py_path.exists():
        py_path.parent.mkdir(parents=True, exist_ok=True)
        # 创建基础文件
        if var_name == 'HOTWORDS':
            header = '# 热词配置\n# 以 # 开头的行为注释，会被忽略\n\nHOTWORDS = []\n'
        elif var_name == 'RECTIFICATIONS':
            header = '# 纠错历史配置\n# 每条记录是一个字典，包含 "wrong" 和 "right"\n\nRECTIFICATIONS = []\n'
        else:
            header = f'# 配置\n\n{var_name} = []\n'
        py_path.write_text(header, encoding='utf-8')

    with open(py_path, 'a', encoding='utf-8') as f:
        f.write(f'\n{var_name}.append({repr(value)})\n')
